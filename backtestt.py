import time
import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import logging
import os
import configparser
from typing import Dict, List, Tuple, Optional
import random
from tqdm import tqdm
import itertools
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("CryptoTradingBot")

class CryptoTradingBot:
    def __init__(self, 
                 api_key: str = None, 
                 api_secret: str = None, 
                 total_balance: float = 1000.0,
                 tkm_percentage: float = 10.0,
                 entry_price_percentage: float = 2.0,
                 leverage: int = 5,
                 margin_loss_roi_levels: List[float] = [200, 200, 200, 200],
                 margin_increase_levels: List[float] = [100, 50, 33, 25],
                 take_profit_roi: float = 200.0,
                 counter_trade_loss_roi: float = 500.0,
                 counter_trade_margin_percentage: float = 100.0,
                 position_direction: str = "SHORT",
                 detection_period_minutes: int = 45,
                 pump_dump_threshold: float = 7.0,
                 backtest_mode: bool = False):
        """
        Initialize the crypto trading bot with the specified parameters.
        
        Parameters:
        - api_key: Exchange API key (optional for backtest)
        - api_secret: Exchange API secret (optional for backtest)
        - total_balance: Total available balance for trading
        - tkm_percentage: Total margin to be used (as percentage of total balance)
        - entry_price_percentage: Initial entry percentage
        - leverage: Leverage ratio for trades (e.g., 5x)
        - margin_loss_roi_levels: List of ROI percentages for margin addition levels
        - margin_increase_levels: List of margin increase percentages for each level
        - take_profit_roi: Take profit ROI percentage
        - counter_trade_loss_roi: Counter trade loss ROI percentage
        - counter_trade_margin_percentage: Counter trade margin percentage
        - position_direction: Trading direction (LONG or SHORT)
        - detection_period_minutes: Period to detect pump/dump in minutes
        - pump_dump_threshold: Percentage change to trigger trade
        - backtest_mode: Whether to run in backtest mode
        """
        if not backtest_mode and (api_key is None or api_secret is None):
            raise ValueError("API key and secret are required for live trading")
            
        self.backtest_mode = backtest_mode
        
        if not backtest_mode:
            self.exchange = ccxt.binance({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future',  # Use futures market
                }
            })
        else:
            self.exchange = None
        
        # Trading parameters
        self.total_balance = total_balance
        self.current_balance = total_balance  # Track balance for backtesting
        self.tkm_percentage = tkm_percentage
        self.tkm = total_balance * (tkm_percentage / 100)
        self.entry_price_percentage = entry_price_percentage
        self.leverage = leverage
        self.margin_loss_roi_levels = margin_loss_roi_levels
        self.margin_increase_levels = margin_increase_levels
        self.take_profit_roi = take_profit_roi
        self.counter_trade_loss_roi = counter_trade_loss_roi
        self.counter_trade_margin_percentage = counter_trade_margin_percentage
        self.position_direction = position_direction
        
        # Coin detection parameters
        self.detection_period_minutes = detection_period_minutes
        self.pump_dump_threshold = pump_dump_threshold
        
        # Internal state
        self.active_position = None
        self.counter_trade_position = None
        
        # For backtesting
        self.trade_history = []
        self.equity_curve = []
        self.margin_additions = []
        self.counter_trades = []
        
        # Validate margin increase percentages
        if not backtest_mode:
            self._validate_margin_percentages()
            self._check_hedge_mode()
            
        logger.info(f"Bot initialized with: TKM={tkm_percentage}%, Entry={entry_price_percentage}%, "
                   f"Leverage={leverage}x, Direction={position_direction}, "
                   f"Pump/Dump threshold={pump_dump_threshold}%")
    
    def _validate_margin_percentages(self):
        """Validate that margin increase percentages sum up correctly to match TKM."""
        # Initial entry percentage
        total_used = self.entry_price_percentage
        
        # Calculate how much each margin addition contributes
        current_margin = self.entry_price_percentage
        for increase_percentage in self.margin_increase_levels:
            margin_addition = current_margin * (increase_percentage / 100)
            total_used += margin_addition
            current_margin += margin_addition
        
        # Check if total matches TKM (with small tolerance for floating point errors)
        if abs(total_used - self.tkm_percentage) > 0.01:
            error_msg = (f"Margin percentages do not add up to TKM. "
                        f"Total used: {total_used}%, TKM: {self.tkm_percentage}%")
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info(f"Margin percentage validation passed. Total: {total_used}%")
    
    def _check_hedge_mode(self):
        """Check if hedge mode is enabled and warn if not."""
        try:
            # Get account trading mode
            account_info = self.exchange.fapiPrivateGetPositionSideDual()
            
            if not account_info.get('dualSidePosition', False):
                hedge_warning = "HEDGE MODE IS NOT ENABLED! Please enable hedge mode in your Binance futures account."
                logger.warning(hedge_warning)
                print(f"\n⚠️ WARNING: {hedge_warning}\n")
            else:
                logger.info("Hedge mode is correctly enabled.")
        except Exception as e:
            logger.error(f"Error checking hedge mode: {e}")
            
    # Backtest methods
    def run_backtest(self, historical_data: pd.DataFrame, config: dict = None) -> dict:
        """
        Run a backtest using historical data.
        
        Parameters:
        - historical_data: DataFrame with OHLCV data
        - config: Optional config to override instance parameters
        
        Returns:
        - dict with backtest results
        """
        if config:
            # Override instance parameters with provided config
            for key, value in config.items():
                setattr(self, key, value)
            
            # Recalculate tkm
            self.tkm = self.total_balance * (self.tkm_percentage / 100)
            
        # Reset state for backtest
        self.active_position = None
        self.counter_trade_position = None
        self.current_balance = self.total_balance
        self.trade_history = []
        self.equity_curve = [{"timestamp": historical_data.index[0], "balance": self.current_balance}]
        self.margin_additions = []
        self.counter_trades = []
        
        # Process each candle
        for i in range(self.detection_period_minutes, len(historical_data)):
            # Current candle
            current_time = historical_data.index[i]
            current_price = historical_data.iloc[i]['close']
            
            # Record equity for this timestamp
            self.equity_curve.append({
                "timestamp": current_time,
                "balance": self.current_balance
            })
            
            # If we have an active position, check it
            if self.active_position:
                self._backtest_check_position(current_time, current_price)
            else:
                # Check for entry signal
                detection_window = historical_data.iloc[i-self.detection_period_minutes:i]
                start_price = detection_window.iloc[0]['close']
                end_price = detection_window.iloc[-1]['close']
                
                change_percentage = ((end_price - start_price) / start_price) * 100
                
                # For LONG positions, look for coins that have dumped
                if self.position_direction == "LONG" and change_percentage <= -self.pump_dump_threshold:
                    self._backtest_open_position(current_time, current_price, historical_data.iloc[i]['symbol'])
                    
                # For SHORT positions, look for coins that have pumped
                elif self.position_direction == "SHORT" and change_percentage >= self.pump_dump_threshold:
                    self._backtest_open_position(current_time, current_price, historical_data.iloc[i]['symbol'])
        
        # Close any open position at the end
        if self.active_position:
            final_price = historical_data.iloc[-1]['close']
            self._backtest_close_position(historical_data.index[-1], final_price, "end_of_backtest")
        
        # Calculate backtest results
        results = self._calculate_backtest_results()
        
        return results
    
    def _backtest_open_position(self, timestamp, price, symbol):
        """Open a position in backtest mode."""
        # Calculate quantity based on entry percentage and leverage
        initial_margin = self.current_balance * (self.entry_price_percentage / 100)
        quantity = (initial_margin * self.leverage) / price
        
        # Store position information
        self.active_position = {
            'coin': symbol,
            'entry_time': timestamp,
            'entry_price': price,
            'quantity': quantity,
            'direction': self.position_direction,
            'current_margin': initial_margin,
            'margin_level': 0,  # Starting at level 0
            'total_margin_used': self.entry_price_percentage  # Track total margin percentage used
        }
        
        # Calculate take profit and stop loss
        effective_tp_percentage = self.take_profit_roi / self.leverage
        effective_sl_percentage = self.margin_loss_roi_levels[0] / self.leverage
        
        if self.position_direction == "LONG":
            take_profit_price = price * (1 + effective_tp_percentage / 100)
            stop_loss_price = price * (1 - effective_sl_percentage / 100)
        else:  # SHORT
            take_profit_price = price * (1 - effective_tp_percentage / 100)
            stop_loss_price = price * (1 + effective_sl_percentage / 100)
            
        self.active_position['take_profit_price'] = take_profit_price
        self.active_position['stop_loss_price'] = stop_loss_price
        
        # Log trade
        trade_log = {
            'action': 'open',
            'time': timestamp,
            'coin': symbol,
            'direction': self.position_direction,
            'price': price,
            'quantity': quantity,
            'margin': initial_margin
        }
        self.trade_history.append(trade_log)
        
        logger.debug(f"Backtest: Opened {self.position_direction} position at {price}")
    
    def _backtest_add_margin(self, timestamp, price):
        """Add margin in backtest mode."""
        current_level = self.active_position['margin_level']
        
        # Check if we've already used all margin levels
        if current_level >= len(self.margin_increase_levels):
            return False
            
        # Calculate additional margin
        current_margin = self.active_position['current_margin']
        margin_increase_percentage = self.margin_increase_levels[current_level]
        additional_margin = current_margin * (margin_increase_percentage / 100)
        
        # Update position with new margin
        new_total_margin = current_margin + additional_margin
        
        # Calculate additional quantity
        additional_quantity = (additional_margin * self.leverage) / price
        
        # Update position information
        self.active_position['quantity'] += additional_quantity
        self.active_position['current_margin'] = new_total_margin
        self.active_position['margin_level'] += 1
        
        # Track total margin percentage used
        margin_percentage_added = (additional_margin / self.total_balance) * 100
        self.active_position['total_margin_used'] += margin_percentage_added
        
        # Update stop loss level for the next margin level
        if self.active_position['margin_level'] < len(self.margin_loss_roi_levels):
            next_roi = self.margin_loss_roi_levels[self.active_position['margin_level']]
            effective_sl_percentage = next_roi / self.leverage
            
            if self.active_position['direction'] == "LONG":
                self.active_position['stop_loss_price'] = self.active_position['entry_price'] * (1 - effective_sl_percentage / 100)
            else:  # SHORT
                self.active_position['stop_loss_price'] = self.active_position['entry_price'] * (1 + effective_sl_percentage / 100)
        
        # Log margin addition
        margin_log = {
            'time': timestamp,
            'level': self.active_position['margin_level'],
            'amount': additional_margin,
            'total_margin': new_total_margin,
            'price': price
        }
        self.margin_additions.append(margin_log)
        
        logger.debug(f"Backtest: Added margin level {self.active_position['margin_level']} at {price}")
        return True
    
    def _backtest_open_counter_trade(self, timestamp, price):
        """Open a counter trade in backtest mode."""
        if self.counter_trade_position:
            return False
            
        # Calculate counter trade margin
        counter_margin = self.total_balance * (self.counter_trade_margin_percentage / 100)
        
        # Calculate quantity with leverage
        quantity = (counter_margin * self.leverage) / price
        
        # Determine direction (opposite of original position)
        counter_direction = "SHORT" if self.active_position['direction'] == "LONG" else "LONG"
        
        # Store counter position information
        self.counter_trade_position = {
            'entry_time': timestamp,
            'entry_price': price,
            'quantity': quantity,
            'direction': counter_direction,
            'margin': counter_margin
        }
        
        # Log counter trade
        counter_log = {
            'time': timestamp,
            'direction': counter_direction,
            'price': price,
            'quantity': quantity,
            'margin': counter_margin
        }
        self.counter_trades.append(counter_log)
        
        logger.debug(f"Backtest: Opened counter trade {counter_direction} at {price}")
        return True
    
    def _backtest_close_counter_trade(self, timestamp, price):
        """Close counter trade in backtest mode."""
        if not self.counter_trade_position:
            return False
            
        # Calculate profit/loss
        entry_price = self.counter_trade_position['entry_price']
        
        if self.counter_trade_position['direction'] == "LONG":
            pnl_percentage = ((price - entry_price) / entry_price) * 100 * self.leverage
            pnl_amount = self.counter_trade_position['margin'] * (pnl_percentage / 100)
        else:  # SHORT
            pnl_percentage = ((entry_price - price) / entry_price) * 100 * self.leverage
            pnl_amount = self.counter_trade_position['margin'] * (pnl_percentage / 100)
        
        # Update balance
        self.current_balance += pnl_amount
        
        # Log counter trade close
        counter_close_log = {
            'time': timestamp,
            'action': 'close_counter',
            'direction': self.counter_trade_position['direction'],
            'open_price': entry_price,
            'close_price': price,
            'pnl_percentage': pnl_percentage,
            'pnl_amount': pnl_amount
        }
        self.trade_history.append(counter_close_log)
        
        # Reset counter trade position
        self.counter_trade_position = None
        
        logger.debug(f"Backtest: Closed counter trade at {price}, PnL: {pnl_percentage:.2f}%")
        return True
    
    def _backtest_close_position(self, timestamp, price, reason):
        """Close position in backtest mode."""
        if not self.active_position:
            return False
            
        # Close counter trade if exists
        if self.counter_trade_position:
            self._backtest_close_counter_trade(timestamp, price)
        
        # Calculate profit/loss
        entry_price = self.active_position['entry_price']
        
        if self.active_position['direction'] == "LONG":
            pnl_percentage = ((price - entry_price) / entry_price) * 100 * self.leverage
            pnl_amount = self.active_position['current_margin'] * (pnl_percentage / 100)
        else:  # SHORT
            pnl_percentage = ((entry_price - price) / entry_price) * 100 * self.leverage
            pnl_amount = self.active_position['current_margin'] * (pnl_percentage / 100)
        
        # Update balance
        self.current_balance += pnl_amount
        
        # Log trade close
        close_log = {
            'time': timestamp,
            'action': 'close',
            'reason': reason,
            'open_price': entry_price,
            'close_price': price,
            'pnl_percentage': pnl_percentage,
            'pnl_amount': pnl_amount,
            'margin_levels_used': self.active_position['margin_level'],
            'total_margin_used': self.active_position['total_margin_used']
        }
        self.trade_history.append(close_log)
        
        # Reset position
        self.active_position = None
        
        logger.debug(f"Backtest: Closed position at {price}, Reason: {reason}, PnL: {pnl_percentage:.2f}%")
        return True
    
    def _backtest_check_position(self, timestamp, price):
        """Check position in backtest mode."""
        if not self.active_position:
            return
            
        # Check take profit condition
        if ((self.active_position['direction'] == "LONG" and price >= self.active_position['take_profit_price']) or
            (self.active_position['direction'] == "SHORT" and price <= self.active_position['take_profit_price'])):
            self._backtest_close_position(timestamp, price, "take_profit")
            return
            
        # Check stop loss condition
        if ((self.active_position['direction'] == "LONG" and price <= self.active_position['stop_loss_price']) or
            (self.active_position['direction'] == "SHORT" and price >= self.active_position['stop_loss_price'])):
            
            # Check if we can add more margin
            if self.active_position['margin_level'] < len(self.margin_increase_levels):
                self._backtest_add_margin(timestamp, price)
            else:
                # If all margin levels used, manage with counter trades
                self._backtest_manage_counter_trade(timestamp, price)
    
    def _backtest_manage_counter_trade(self, timestamp, price):
        """Manage counter trade in backtest mode."""
        if not self.active_position:
            return
            
        # Calculate current ROI (with leverage effect)
        entry_price = self.active_position['entry_price']
        
        if self.active_position['direction'] == "LONG":
            roi = ((entry_price - price) / entry_price) * 100 * self.leverage
        else:  # SHORT
            roi = ((price - entry_price) / entry_price) * 100 * self.leverage
            
        # Check if ROI exceeds the counter trade threshold
        if roi >= self.counter_trade_loss_roi:
            # If we don't have a counter trade yet, open one
            if not self.counter_trade_position:
                self._backtest_open_counter_trade(timestamp, price)
        else:
            # If ROI falls below threshold and we have a counter trade, close it
            if self.counter_trade_position:
                self._backtest_close_counter_trade(timestamp, price)
    
    def _calculate_backtest_results(self):
        """Calculate performance metrics from backtest."""
        # Convert equity curve to DataFrame
        equity_df = pd.DataFrame(self.equity_curve)
        if not equity_df.empty:
            equity_df.set_index('timestamp', inplace=True)
        
        # Calculate trade statistics
        total_trades = len([t for t in self.trade_history if t.get('action') == 'close'])
        winning_trades = len([t for t in self.trade_history if t.get('action') == 'close' and t.get('pnl_amount', 0) > 0])
        losing_trades = len([t for t in self.trade_history if t.get('action') == 'close' and t.get('pnl_amount', 0) <= 0])
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Calculate profit/loss
        initial_balance = self.total_balance
        final_balance = self.current_balance
        absolute_return = final_balance - initial_balance
        percentage_return = (absolute_return / initial_balance) * 100
        
        # Calculate drawdown
        if not equity_df.empty:
            equity_df['cummax'] = equity_df['balance'].cummax()
            equity_df['drawdown'] = (equity_df['balance'] / equity_df['cummax'] - 1) * 100
            max_drawdown = equity_df['drawdown'].min()
        else:
            max_drawdown = 0
        
        # Calculate Sharpe ratio (if more than one data point)
        if len(equity_df) > 1:
            equity_df['returns'] = equity_df['balance'].pct_change()
            sharpe_ratio = equity_df['returns'].mean() / equity_df['returns'].std() * np.sqrt(252)  # Annualized
        else:
            sharpe_ratio = 0
        
        # Create results dictionary
        results = {
            'initial_balance': initial_balance,
            'final_balance': final_balance,
            'absolute_return': absolute_return,
            'percentage_return': percentage_return,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'equity_curve': self.equity_curve,
            'trade_history': self.trade_history,
            'margin_additions': self.margin_additions,
            'counter_trades': self.counter_trades,
            'parameters': {
                'tkm_percentage': self.tkm_percentage,
                'entry_price_percentage': self.entry_price_percentage,
                'leverage': self.leverage,
                'margin_loss_roi_levels': self.margin_loss_roi_levels,
                'margin_increase_levels': self.margin_increase_levels,
                'take_profit_roi': self.take_profit_roi,
                'counter_trade_loss_roi': self.counter_trade_loss_roi,
                'counter_trade_margin_percentage': self.counter_trade_margin_percentage,
                'position_direction': self.position_direction,
                'detection_period_minutes': self.detection_period_minutes,
                'pump_dump_threshold': self.pump_dump_threshold
            }
        }
        
        return results
    
    # Backtest visualization methods
    def plot_equity_curve(self, results: dict, save_path: str = None):
        """Plot equity curve from backtest results."""
        if not results.get('equity_curve'):
            logger.warning("No equity curve data available to plot")
            return
        
        # Create DataFrame from equity curve
        equity_data = pd.DataFrame(results['equity_curve'])
        equity_data.set_index('timestamp', inplace=True)
        
        plt.figure(figsize=(12, 6))
        plt.plot(equity_data.index, equity_data['balance'], label='Balance')
        
        # Plot horizontal line at initial balance
        plt.axhline(y=results['initial_balance'], color='r', linestyle='--', label='Initial Balance')
        
        plt.title('Equity Curve')
        plt.xlabel('Date')
        plt.ylabel('Balance')
        plt.legend()
        plt.grid(True)
        
        if save_path:
            plt.savefig(save_path)
        
        plt.show()
    
    def plot_trade_analysis(self, results: dict, save_path: str = None):
        """Plot detailed trade analysis from backtest results."""
        if not results.get('trade_history'):
            logger.warning("No trade history available to plot")
            return
        
        # Create DataFrame from trade history
        trades = [t for t in results['trade_history'] if t.get('action') == 'close']
        
        if not trades:
            logger.warning("No closed trades found to analyze")
            return
        
        trade_df = pd.DataFrame(trades)
        
        # Convert time to datetime if it's not already
        if trade_df['time'].dtype != 'datetime64[ns]':
            trade_df['time'] = pd.to_datetime(trade_df['time'])
        
        # Set up figure
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        
        # Plot 1: Cumulative P&L
        trade_df['cumulative_pnl'] = trade_df['pnl_amount'].cumsum()
        axes[0, 0].plot(trade_df['time'], trade_df['cumulative_pnl'])
        axes[0, 0].set_title('Cumulative P&L')
        axes[0, 0].set_xlabel('Date')
        axes[0, 0].set_ylabel('Profit/Loss')
        axes[0, 0].grid(True)
        
        # Plot 2: P&L Distribution
        axes[0, 1].hist(trade_df['pnl_percentage'], bins=20)
        axes[0, 1].set_title('P&L Distribution')
        axes[0, 1].set_xlabel('P&L %')
        axes[0, 1].set_ylabel('Frequency')
        axes[0, 1].grid(True)
        
        # Plot 3: P&L by Close Reason
        if 'reason' in trade_df.columns:
            reason_groups = trade_df.groupby('reason')['pnl_amount'].sum()
            axes[1, 0].bar(reason_groups.index, reason_groups.values)
            axes[1, 0].set_title('P&L by Close Reason')
            axes[1, 0].set_xlabel('Reason')
            axes[1, 0].set_ylabel('Total P&L')
            axes[1, 0].grid(True)
        
        # Plot 4: Rolling Win Rate
        window_size = min(10, len(trade_df))
        trade_df['win'] = trade_df['pnl_amount'] > 0
        trade_df['rolling_win_rate'] = trade_df['win'].rolling(window=window_size).mean() * 100
        
        axes[1, 1].plot(trade_df['time'], trade_df['rolling_win_rate'])
        axes[1, 1].set_title(f'Rolling {window_size}-Trade Win Rate')
        axes[1, 1].set_xlabel('Date')
        axes[1, 1].set_ylabel('Win Rate %')
        axes[1, 1].grid(True)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path)
        
        plt.show()
    
    def generate_backtest_report(self, results: dict, save_path: str = None):
        """Generate a comprehensive backtest report."""
        if not results:
            logger.warning("No results available to generate report")
            return
        
        # Create a comprehensive report
        report = "# Crypto Trading Bot Backtest Report\n\n"
        
        # Overall performance metrics
        report += "## Overall Performance\n\n"
        report += f"- Initial Balance: ${results['initial_balance']:.2f}\n"
        report += f"- Final Balance: ${results['final_balance']:.2f}\n"
        report += f"- Absolute Return: ${results['absolute_return']:.2f}\n"
        report += f"- Percentage Return: {results['percentage_return']:.2f}%\n"
        report += f"- Max Drawdown: {results['max_drawdown']:.2f}%\n"
        report += f"- Sharpe Ratio: {results['sharpe_ratio']:.4f}\n\n"
        
        # Trade statistics
        report += "## Trade Statistics\n\n"
        report += f"- Total Trades: {results['total_trades']}\n"
        report += f"- Winning Trades: {results['winning_trades']}\n"
        report += f"- Losing Trades: {results['losing_trades']}\n"
        report += f"- Win Rate: {results['win_rate']:.2f}%\n\n"
        
        # Strategy parameters
        report += "## Strategy Parameters\n\n"
        for key, value in results['parameters'].items():
            report += f"- {key}: {value}\n"
        
        # Save report to file if specified
        if save_path:
            with open(save_path, 'w') as f:
                f.write(report)
            logger.info(f"Backtest report saved to {save_path}")
        
        return report