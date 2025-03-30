import threading
import datetime

class MatchingEngine:
    def __init__(self, database):
        self.database = database
        self.lock = threading.Lock()
    
    def match_orders(self, symbol):
        """匹配指定股票的买卖订单"""
        with self.lock:
            # 获取所有开放订单
            buy_orders = self.database.get_buy_orders(symbol)
            sell_orders = self.database.get_sell_orders(symbol)
            
            # 如果买入或卖出订单为空，则无法匹配
            if not buy_orders or not sell_orders:
                return
            
            # 尝试匹配订单
            with self.database.session_scope() as session:
                while buy_orders and sell_orders:
                    buy_order = buy_orders[0]
                    sell_order = sell_orders[0]
                    
                    # 检查价格是否匹配
                    if buy_order.limit_price < sell_order.limit_price:
                        break  # 无法匹配
                    
                    # 确定执行价格（先开放的订单的价格）
                    if buy_order.created_at < sell_order.created_at:
                        execution_price = buy_order.limit_price
                    else:
                        execution_price = sell_order.limit_price
                    
                    # 确定要执行的股数
                    execute_shares = min(buy_order.open_shares, abs(sell_order.open_shares))
                    
                    # 更新买入订单
                    self.database.execute_order_part(buy_order, execute_shares, execution_price, session)
                    
                    # 更新卖出订单
                    self.database.execute_order_part(sell_order, execute_shares, execution_price, session)
                    
                    # 更新买家仓位
                    self.database.update_position(
                        symbol, buy_order.account_id, execute_shares, session)
                    
                    # 更新卖家余额
                    self.database.update_account_balance(
                        sell_order.account_id, execute_shares * execution_price, session)
                    
                    # 如果订单完全执行，从队列中移除
                    if buy_order.open_shares == 0:
                        buy_orders.pop(0)
                    if sell_order.open_shares == 0:
                        sell_orders.pop(0)
    
    def place_order(self, account_id, symbol, amount, limit_price):
        """下单并尝试匹配"""
        with self.database.session_scope() as session:
            account = session.query(self.database.Account).filter_by(id=account_id).first()
            if not account:
                return False, "Account not found", None
            
            # 买入订单，检查余额是否充足
            if amount > 0:  # 买入
                cost = amount * float(limit_price)
                if account.balance < cost:
                    return False, "Insufficient funds", None
                
                # 扣除余额
                account.balance -= cost
            else:  # 卖出
                # 检查股票是否足够
                position = session.query(self.database.Position).filter_by(
                    account_id=account_id, symbol_name=symbol).first()
                if not position or position.amount < abs(amount):
                    return False, "Insufficient shares", None
                
                # 扣除股票
                position.amount += amount  # amount为负数
            
            # 创建订单
            order = self.database.create_order(account_id, symbol, amount, limit_price)
            
        # 尝试匹配订单
        self.match_orders(symbol)
        
        return True, None, order
