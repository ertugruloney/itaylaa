import streamlit as st
import ccxt.pro as ccxtpro
import ccxt
import asyncio
# import time # Not directly used in the provided async logic that uses asyncio.sleep
import math
import traceback
from datetime import datetime

# --- Global Bot Variables (will be set by Streamlit) ---
API_KEY = ''
API_SECRET = ''
LEVERAGE = 3  # Default, will be overridden by Streamlit input

# Original COINS_TO_TRADE_CONFIG can remain as a default
# This will be used by the bot, taken from the default for this example
COINS_TO_TRADE_CONFIG = [
    {'symbol': 'XRP/USDT', 'collateral_usdt': 5.0, 'trade_sides': 'long_only'},
    {'symbol': 'TRX/USDT', 'collateral_usdt': 5.0, 'trade_sides': 'short_only'},
]

positions_data = {}
exchange = None # Will be initialized in the bot logic

# Save original print
original_print = print

# --- Bot Logging Function ---
def bot_print(*args, **kwargs):
    message = " ".join(map(str, args))
    original_print(message, **kwargs)  # Keep console log
    if 'bot_logs_list' in st.session_state:
        st.session_state.bot_logs_list.append(message)
        # To update the text_area more dynamically, a rerun or other mechanism might be needed.
        # For now, logs accumulate and display on reruns/completion.
    else:
        original_print("! Streamlit log session state not ready for:", message)

# --- Original Bot Functions (Modified to use bot_print and global vars) ---
async def set_leverage_for_symbol(symbol_arg, leverage_arg):
    global exchange
    try:
        await exchange.set_leverage(leverage_arg, symbol_arg)
        bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol_arg} için kaldıraç {leverage_arg}x olarak ayarlandı.")
        return True
    except ccxt.MarginModeAlreadySet:
        try:
            await exchange.set_leverage(leverage_arg, symbol_arg)
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol_arg} için kaldıraç {leverage_arg}x olarak ayarlandı (margin modu mevcut).")
            return True
        except Exception as e_set_leverage_again:
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol_arg} için kaldıraç (margin modu mevcutken) ayarlanamadı: {e_set_leverage_again}")
    except ccxt.ExchangeError as e_ex:
        bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol_arg} için kaldıraç ayarlarken BORSA HATASI: {e_ex}")
    except Exception as e:
        bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol_arg} için kaldıraç ayarlarken bilinmeyen genel hata: {e}")
    return False

async def get_current_position_info(symbol_to_check):
    global exchange
    try:
        fetched_positions_list = await exchange.fetch_positions([symbol_to_check])
        if not fetched_positions_list:
            return None

        for p_raw in fetched_positions_list:
            expected_symbol_in_raw = f"{symbol_to_check}:USDT"
            info_symbol = p_raw.get('info', {}).get('symbol', '').upper()
            market_id = exchange.market(symbol_to_check)['id'].upper()

            if p_raw.get('symbol') == expected_symbol_in_raw or info_symbol == market_id :
                info = p_raw.get('info', {})
                position_amt_str = info.get('positionAmt', '0')
                entry_price_info_str = info.get('entryPrice', '0')
                final_contracts = 0.0
                final_side = None
                final_entry_price = 0.0

                if position_amt_str:
                    try:
                        position_amt_float = float(position_amt_str)
                        if position_amt_float != 0:
                            final_contracts = abs(position_amt_float)
                            final_side = 'long' if position_amt_float > 0 else 'short'
                            
                            if entry_price_info_str:
                                try:
                                    entry_price_from_info_float = float(entry_price_info_str)
                                    if entry_price_from_info_float > 0:
                                        final_entry_price = entry_price_from_info_float
                                except ValueError: pass
                            
                            if final_entry_price == 0.0:
                                entry_price_unified = p_raw.get('entryPrice')
                                if entry_price_unified is not None:
                                    try:
                                        final_entry_price = float(entry_price_unified)
                                        if final_entry_price <= 0: final_entry_price = 0.0
                                    except ValueError: final_entry_price = 0.0
                    except ValueError:
                        bot_print(f"UYARI: {symbol_to_check} için info.positionAmt ({position_amt_str}) float'a çevrilemedi.")
                
                condition_met = final_contracts > 0 and final_side and final_entry_price > 0
                if condition_met:
                    return {'quantity': final_contracts, 'side': final_side, 'entry_price': final_entry_price}
        
        return None
    except Exception as e:
        bot_print(f"HATA: {symbol_to_check} için `get_current_position_info` içinde istisna: {e}")
        bot_print(traceback.format_exc())
        return {'error': str(e)}

async def place_order_and_update_state(symbol, side, collateral_for_trade, current_market_price, coin_side_data):
    global exchange, LEVERAGE
    action = "UZUN" if side == 'buy' else "KISA"
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if current_market_price <= 0:
        bot_print(f"[{timestamp}] {symbol} ({action}) için geçersiz piyasa fiyatı ({current_market_price}), emir verilemiyor.")
        return False

    notional_value_usdt = collateral_for_trade * LEVERAGE
    order_quantity_raw = notional_value_usdt / current_market_price
    
    try:
        order_quantity = float(exchange.amount_to_precision(symbol, order_quantity_raw))
    except Exception as e_prec:
        bot_print(f"[{timestamp}] {symbol} için miktar hassasiyeti ayarlanırken hata: {e_prec}. Ham miktar: {order_quantity_raw}")
        return False

    market_info = exchange.markets[symbol]
    min_amount_limit = market_info.get('limits', {}).get('amount', {}).get('min')
    min_cost_limit = market_info.get('limits', {}).get('cost', {}).get('min')

    if min_amount_limit is not None and order_quantity < min_amount_limit:
        bot_print(f"[{timestamp}] {symbol} ({action}) için hesaplanan miktar ({order_quantity}) minimum ({min_amount_limit}) altında. Emir verilmiyor.")
        return False
    if min_cost_limit is not None and notional_value_usdt < min_cost_limit:
        bot_print(f"[{timestamp}] {symbol} ({action}) için hesaplanan notional değer ({notional_value_usdt:.2f} USDT) minimum ({min_cost_limit} USDT) altında. Emir verilmiyor.")
        return False
    if order_quantity <= 0:
        bot_print(f"[{timestamp}] {symbol} ({action}) için hesaplanan miktar sıfır veya negatif ({order_quantity}). Emir verilmiyor.")
        return False

    bot_print(f"[{timestamp}] {symbol} için {collateral_for_trade:.2f} USDT teminat, {LEVERAGE}x kaldıraç ile ~{order_quantity:.8f} {market_info.get('base','COIN')} miktarında {action} pozisyon girilmeye çalışılıyor (Piyasa Fiyatı: {current_market_price})...")
    
    try:
        created_order = None
        if side == 'buy':
            created_order = await exchange.create_market_buy_order(symbol, order_quantity)
        else:
            created_order = await exchange.create_market_sell_order(symbol, order_quantity)
        await asyncio.sleep(1.5) 
        updated_position_info = await get_current_position_info(symbol)
        filled_price = 0.0
        if updated_position_info and not updated_position_info.get('error'):
            expected_side = "long" if side == 'buy' else "short"
            if updated_position_info['side'] == expected_side:
                filled_price = updated_position_info['entry_price']
        if filled_price == 0.0 and created_order: 
             if created_order.get('average') and created_order['average'] > 0:
                filled_price = float(created_order['average'])
             elif created_order.get('price') and created_order['price'] > 0:
                filled_price = float(created_order['price'])
             elif created_order.get('filled') and created_order.get('cost') and created_order['filled'] > 0:
                filled_price = float(created_order['cost']) / float(created_order['filled'])
        if filled_price > 0:
            coin_side_data['in_position'] = True
            coin_side_data['current_position_actual_entry_price'] = filled_price
            bot_print(f"[{timestamp}] {symbol} için {action} pozisyona girildi. Gerçekleşen Giriş Fiyatı: {filled_price:.4f}")
            if coin_side_data['first_trade_actual_entry_price'] is None:
                coin_side_data['first_trade_actual_entry_price'] = filled_price
                bot_print(f"[{timestamp}] {symbol} ({action}) için bu ilk işlem. Referans giriş fiyatı {filled_price:.4f} olarak ayarlandı.")
            return True
        else:
            bot_print(f"[{timestamp}] {symbol} ({action}) için emir verildi ancak dolum fiyatı/pozisyon teyidi alınamadı. Emir ID: {created_order.get('id') if created_order else 'N/A'}")
            return False
    except ccxt.InsufficientFunds as e:
        bot_print(f"[{timestamp}] {symbol} ({action}) pozisyonuna girerken YETERSİZ BAKİYE: {e}")
    except ccxt.NetworkError as e:
        bot_print(f"[{timestamp}] {symbol} ({action}) pozisyonuna girerken AĞ HATASI: {e}")
    except ccxt.ExchangeError as e:
        bot_print(f"[{timestamp}] {symbol} ({action}) pozisyonuna girerken BORSA HATASI: {e} (Miktar: {order_quantity})")
    except Exception as e:
        bot_print(f"[{timestamp}] {symbol} ({action}) pozisyonuna girerken BİLİNMEYEN HATA: {e}")
        bot_print(traceback.format_exc())
    return False

async def close_order_and_update_state(symbol, side_to_close, coin_side_data):
    global exchange
    action = "UZUN" if side_to_close == 'long' else "KISA"
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    bot_print(f"[{timestamp}] {symbol} için {action} pozisyon ({coin_side_data.get('current_position_actual_entry_price', 'N/A')}) kapatılmaya çalışılıyor...")

    position_info = await get_current_position_info(symbol)

    if position_info and not position_info.get('error') and position_info['side'] == side_to_close:
        quantity_to_close = position_info['quantity']
        try:
            quantity_to_close_formatted = float(exchange.amount_to_precision(symbol, quantity_to_close))
        except Exception as e_prec_close:
            bot_print(f"[{timestamp}] Kapatma miktarını formatlarken hata {symbol}: {e_prec_close}. Ham miktar: {quantity_to_close}")
            return False
        if quantity_to_close_formatted <= 0:
            bot_print(f"[{timestamp}] {symbol} ({action}) kapatılacak pozisyon miktarı sıfır. Pozisyon zaten kapalı olabilir.")
            coin_side_data['in_position'] = False
            return True
        bot_print(f"[{timestamp}] {symbol} ({action}) kapatılacak miktar: {quantity_to_close_formatted}")
        try:
            if side_to_close == 'long':
                await exchange.create_market_sell_order(symbol, quantity_to_close_formatted, {'reduceOnly': True})
            else: 
                await exchange.create_market_buy_order(symbol, quantity_to_close_formatted, {'reduceOnly': True})
            coin_side_data['in_position'] = False
            bot_print(f"[{timestamp}] {symbol} için {action} pozisyon kapatma emri verildi.")
            await asyncio.sleep(1.5) 
            final_pos_check = await get_current_position_info(symbol)
            if not final_pos_check or final_pos_check.get('error') or final_pos_check.get('side') != side_to_close:
                 bot_print(f"[{timestamp}] {symbol} ({action}) pozisyonu kapatıldıktan sonra teyit edildi (veya hata/yön değişikliği).")
            else:
                 bot_print(f"[{timestamp}] UYARI: {symbol} ({action}) pozisyonu kapatma emri sonrası hala aktif görünüyor: {final_pos_check}")
            return True
        except ccxt.ExchangeError as e:
            if "reduceonly" in str(e).lower() or "position side does not match" in str(e).lower() or "order would not reduce position size" in str(e).lower():
                bot_print(f"[{timestamp}] {symbol} ({action}) pozisyonu kapatılırken borsa hatası (muhtemelen zaten kapalı): {e}. Durum güncelleniyor.")
                coin_side_data['in_position'] = False 
                return True 
            bot_print(f"[{timestamp}] {symbol} ({action}) pozisyonunu kapatırken BORSA HATASI: {e}")
        except Exception as e:
            bot_print(f"[{timestamp}] {symbol} ({action}) pozisyonunu kapatırken BİLİNMEYEN HATA: {e}")
            bot_print(traceback.format_exc())
        return False
    elif position_info and position_info.get('error'):
        bot_print(f"[{timestamp}] {symbol} ({action}) pozisyonu kapatılamadı, pozisyon bilgisi alınırken hata: {position_info.get('error')}")
        return False
    else:
        bot_print(f"[{timestamp}] {symbol} ({action}) kapatılacak aktif pozisyon bulunamadı veya yön eşleşmiyor (API yanıtı: {position_info}). Pozisyon zaten kapalı olabilir.")
        coin_side_data['in_position'] = False 
        return True

async def trade_coin_logic(symbol_config):
    global exchange, positions_data, LEVERAGE
    symbol = symbol_config['symbol']
    coin_data = positions_data[symbol]
    trade_sides_preference = symbol_config.get('trade_sides', 'both').lower()
    start_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    bot_print(f"[{start_timestamp}] {symbol} için ticaret mantığı başlatılıyor. Teminat: {coin_data['long']['collateral_usdt']:.2f} USDT, İşlem Yönleri: {trade_sides_preference.upper()}")
    
    # Check for stop request before setting leverage, though less critical here
    if st.session_state.get('stop_requested', False):
        bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için başlangıçta durdurma isteği algılandı.")
        return

    await set_leverage_for_symbol(symbol, LEVERAGE)

    while True:
        # *** ADDED: Check for stop request at the beginning of each loop iteration ***
        if st.session_state.get('stop_requested', False):
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için durdurma isteği alındı, ticaret döngüsü sonlandırılıyor.")
            break # Exit the while True loop

        try:
            ticker = await exchange.watch_ticker(symbol)
            last_known_price = float(ticker['last'])
            current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            long_status = "AKTİF" if coin_data['long']['in_position'] else "DEĞİL"
            short_status = "AKTİF" if coin_data['short']['in_position'] else "DEĞİL"
            
            # Limit frequent logging if not in position or price hasn't changed much (optional optimization)
            # For now, logging every ticker.
            bot_print(f"[{current_timestamp}] {symbol}: Fyt={last_known_price:.4f} | LongPoz: {long_status} (Giriş: {coin_data['long']['current_position_actual_entry_price'] if coin_data['long']['in_position'] else 'N/A'}) | ShortPoz: {short_status} (Giriş: {coin_data['short']['current_position_actual_entry_price'] if coin_data['short']['in_position'] else 'N/A'})")

            if not last_known_price or last_known_price <= 0:
                await asyncio.sleep(1)
                continue

            # Check stop request before placing or closing orders
            if st.session_state.get('stop_requested', False): break

            if trade_sides_preference in ['both', 'long_only']:
                long_data = coin_data['long']
                long_entry_target = long_data['first_trade_actual_entry_price'] if long_data['first_trade_actual_entry_price'] is not None else long_data['initial_target_price']
                if not long_data['in_position']:
                    if last_known_price > long_entry_target:
                        bot_print(f"[{current_timestamp}] LONG GİRİŞ SİNYALİ: {symbol} Fyt({last_known_price:.4f}) > Hdf({long_entry_target:.4f})")
                        await place_order_and_update_state(symbol, 'buy', long_data['collateral_usdt'], last_known_price, long_data)
                elif long_data['in_position'] and last_known_price < long_data['current_position_actual_entry_price']:
                    bot_print(f"[{current_timestamp}] LONG ÇIKIŞ SİNYALİ: {symbol} Fyt({last_known_price:.4f}) < Grş({long_data['current_position_actual_entry_price']:.4f})")
                    await close_order_and_update_state(symbol, 'long', long_data)
            
            if st.session_state.get('stop_requested', False): break # Check again after long logic

            if trade_sides_preference in ['both', 'short_only']:
                short_data = coin_data['short']
                short_entry_target = short_data['first_trade_actual_entry_price'] if short_data['first_trade_actual_entry_price'] is not None else short_data['initial_target_price']
                if not short_data['in_position']:
                    if last_known_price < short_entry_target:
                        bot_print(f"[{current_timestamp}] SHORT GİRİŞ SİNYALİ: {symbol} Fyt({last_known_price:.4f}) < Hdf({short_entry_target:.4f})")
                        await place_order_and_update_state(symbol, 'sell', short_data['collateral_usdt'], last_known_price, short_data)
                elif short_data['in_position'] and last_known_price > short_data['current_position_actual_entry_price']:
                    bot_print(f"[{current_timestamp}] SHORT ÇIKIŞ SİNYALİ: {symbol} Fyt({last_known_price:.4f}) > Grş({short_data['current_position_actual_entry_price']:.4f})")
                    await close_order_and_update_state(symbol, 'short', short_data)
            
            rate_limit_delay = 0.5 
            if hasattr(exchange, 'rateLimit') and exchange.rateLimit and exchange.rateLimit > 0:
                rate_limit_delay = exchange.rateLimit / 1000
            
            # Check stop request before sleep
            if st.session_state.get('stop_requested', False): break
            await asyncio.sleep(max(0.3, rate_limit_delay))

        except ccxt.NetworkError as e:
            # *** ADDED: Check for stop request in exception handlers before long sleeps/retries ***
            if st.session_state.get('stop_requested', False):
                bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için durdurma isteği sırasında ağ hatası, çıkılıyor: {e}")
                break
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için WebSocket bağlantı hatası: {e}. Yeniden bağlanmaya çalışılacak...")
            await asyncio.sleep(5) # Consider stop request for long sleeps
        except ccxt.ExchangeError as e:
            if st.session_state.get('stop_requested', False):
                bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için durdurma isteği sırasında borsa hatası, çıkılıyor: {e}")
                break
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için işlem döngüsünde borsa hatası: {e}")
            if any(err_msg in str(e).lower() for err_msg in ['api key', 'invalid key', 'authentication']):
                 bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için API anahtarı/yetkilendirme sorunu. Bu coin için işlem durduruluyor.")
                 return # Stop this specific coin's task
            await asyncio.sleep(5)
        except Exception as e:
            if st.session_state.get('stop_requested', False):
                bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için durdurma isteği sırasında genel hata, çıkılıyor: {e}")
                break
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için fiyat izleyicide BEKLENMEDİK HATA: {e}")
            bot_print(traceback.format_exc())
            await asyncio.sleep(10) # Consider stop request for long sleeps
    
    bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} ticaret mantığı sonlandı.")


async def run_bot_main_logic():
    global exchange, positions_data, API_KEY, API_SECRET, LEVERAGE, COINS_TO_TRADE_CONFIG

    bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot ana mantığı başlatılıyor. API Key: {'*' * (len(API_KEY)-4) + API_KEY[-4:] if len(API_KEY) > 4 else '***'}, Leverage: {LEVERAGE}x")

    # *** ADDED: Ensure stop_requested is False at the very beginning of a run ***
    # This is also handled by the start button logic, but good for robustness.
    if 'stop_requested' in st.session_state:
        st.session_state.stop_requested = False

    exchange = ccxtpro.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'options': {
            'defaultType': 'future',
        },
        'enableRateLimit': True,
    })

    positions_data = {}
    for coin_conf in COINS_TO_TRADE_CONFIG:
        symbol = coin_conf['symbol']
        collateral = coin_conf['collateral_usdt']
        positions_data[symbol] = {
            'long': { 'in_position': False, 'current_position_actual_entry_price': 0.0, 'first_trade_actual_entry_price': None, 'collateral_usdt': collateral, 'initial_target_price': 0.0 },
            'short': { 'in_position': False, 'current_position_actual_entry_price': 0.0, 'first_trade_actual_entry_price': None, 'collateral_usdt': collateral, 'initial_target_price': float('inf') }
        }
    
    try:
        bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Piyasalar yükleniyor...")
        await exchange.load_markets()
        bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Piyasalar yüklendi.")
        
        # Check for stop request before starting tasks
        if st.session_state.get('stop_requested', False):
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Durdurma isteği görevler başlatılmadan önce algılandı.")
            return # Exit early

        active_tasks = []
        for coin_config_item in COINS_TO_TRADE_CONFIG:
            # Check stop request before creating each task
            if st.session_state.get('stop_requested', False):
                bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Durdurma isteği {coin_config_item['symbol']} için görev oluşturulmadan önce algılandı.")
                break 
            active_tasks.append(trade_coin_logic(coin_config_item))
        
        if active_tasks:
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {len(active_tasks)} adet coin için ticaret görevleri başlatılıyor...")
            await asyncio.gather(*active_tasks)
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Tüm ticaret görevleri tamamlandı.")
        else:
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] İşlem yapılacak coin bulunamadı veya görevler durdurma isteği nedeniyle başlatılmadı.")

    except Exception as e_main:
        bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ana programda HATA: {e_main}")
        bot_print(traceback.format_exc())
    finally:
        if exchange and hasattr(exchange, 'close'):
            try:
                await exchange.close()
                bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exchange bağlantısı kapatıldı.")
            except Exception as e_close:
                bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exchange bağlantısını kapatırken hata: {e_close}")
        bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot ana mantığı sonlandı.")


# --- Streamlit App Definition ---
def streamlit_app():
    global API_KEY, API_SECRET, LEVERAGE, COINS_TO_TRADE_CONFIG 

    st.set_page_config(layout="wide", page_title="Futures Trading Bot")
    st.title("📈 Binance Futures Trading Bot")
    st.caption(f"Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Initialize session state variables
    if 'bot_running' not in st.session_state:
        st.session_state.bot_running = False
    if 'bot_logs_list' not in st.session_state:
        st.session_state.bot_logs_list = ["Bot logs will appear here..."]
    if 'run_bot_triggered' not in st.session_state: 
        st.session_state.run_bot_triggered = False
    if 'api_key' not in st.session_state:
        st.session_state.api_key = ""
    if 'api_secret' not in st.session_state:
        st.session_state.api_secret = ""
    if 'leverage' not in st.session_state:
        st.session_state.leverage = LEVERAGE 
    # *** ADDED: Initialize stop_requested in session state ***
    if 'stop_requested' not in st.session_state:
        st.session_state.stop_requested = False


    with st.sidebar:
        st.header("⚙️ Bot Configuration")
        st.session_state.api_key = st.text_input("Binance API Key", value=st.session_state.api_key, type="password", help="Your Binance API Key for futures trading.")
        st.session_state.api_secret = st.text_input("Binance API Secret", value=st.session_state.api_secret, type="password", help="Your Binance API Secret for futures trading.")
        st.session_state.leverage = st.number_input("Leverage", min_value=1, max_value=125, value=st.session_state.leverage, step=1, help="Leverage to be used for trades (e.g., 3 for 3x).")
        
        st.subheader("Trading Pairs")
        st.json(COINS_TO_TRADE_CONFIG) 
        st.caption("Trading pair configuration is currently fixed in the code.")

        col1, col2 = st.columns(2)
        with col1:
            start_button_disabled = st.session_state.bot_running
            if st.button("🚀 Start Trading Bot", disabled=start_button_disabled, type="primary", use_container_width=True):
                if not st.session_state.api_key or not st.session_state.api_secret:
                    st.error("❌ API Key and API Secret are required.")
                else:
                    API_KEY = st.session_state.api_key
                    API_SECRET = st.session_state.api_secret
                    LEVERAGE = st.session_state.leverage
                    
                    st.session_state.bot_running = True
                    st.session_state.run_bot_triggered = True 
                    st.session_state.stop_requested = False # *** IMPORTANT: Reset stop request on new start ***
                    st.session_state.bot_logs_list = [f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot başlatılıyor..."]
                    st.experimental_rerun() 

        with col2:
            # *** ADDED: Stop Bot Button ***
            stop_button_disabled = not st.session_state.bot_running
            if st.button("🛑 Stop Trading Bot", disabled=stop_button_disabled, type="secondary", use_container_width=True, help="Signals the bot to attempt a graceful shutdown."):
                if st.session_state.bot_running:
                    bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🛑 Stop signal received. Attempting graceful shutdown...")
                    st.session_state.stop_requested = True
                    # The bot will stop its tasks, then bot_running will be set to False in the finally block.
                    # Rerun to update logs and potentially button states if needed sooner.
                    st.experimental_rerun()
                else:
                    st.warning("Bot is not currently running.")


    st.header("📋 Bot Logs")
    log_display_area = st.empty()
    log_display_area.text_area("Logs", value="\n".join(st.session_state.bot_logs_list), height=500, key="log_display_text_area", help="Real-time logs from the trading bot.")

    if st.session_state.bot_running and st.session_state.run_bot_triggered:
        st.session_state.run_bot_triggered = False 
        
        API_KEY = st.session_state.api_key
        API_SECRET = st.session_state.api_secret
        LEVERAGE = st.session_state.leverage

        st.info(f"⏳ Bot is attempting to run with Leverage: {LEVERAGE}x. API Key: {'Set' if API_KEY else 'Not Set'}. Check logs for progress.")
        
        try:
            asyncio.run(run_bot_main_logic())
            # This log will appear after asyncio.run() completes, meaning all tasks finished or were stopped.
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Bot main logic completed or all tasks stopped.")
        except RuntimeError as e_rt:
            if "cannot schedule new futures after shutdown" in str(e_rt) or "Event loop is closed" in str(e_rt):
                 bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Event loop runtime issue, possibly due to restart or prior closure: {e_rt}")
            else:
                bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 💥 Streamlit bot runtime HATA: {e_rt}")
                bot_print(traceback.format_exc())
        except Exception as e:
            bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 💥 Streamlit bot çalıştırma sırasında genel HATA: {e}")
            bot_print(traceback.format_exc())
        finally:
            st.session_state.bot_running = False 
            # If stop was requested, it might have already been logged by the bot logic.
            # This confirms the overall process is winding down.
            if st.session_state.get('stop_requested', False):
                 bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot durdurma işlemi tamamlandı.")
            else:
                 bot_print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot normal şekilde sonlandı veya bir hata nedeniyle durdu.")

            st.session_state.stop_requested = False # Reset for next potential run
            log_display_area.text_area("Logs", value="\n".join(st.session_state.bot_logs_list), height=500, key="log_display_final_update_after_stop") # Use a different key or same, ensure update
            st.warning("🔴 Bot has stopped. Check logs for details. Configure and start again if needed.")
            st.experimental_rerun() 

if __name__ == '__main__':
    streamlit_app()