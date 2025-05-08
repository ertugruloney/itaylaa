import ccxt.pro as ccxtpro
import ccxt
import asyncio
import time # trade_coin_logic içindeki time.sleep(2) için. Eğer gerekmiyorsa kaldırılabilir.
import math
import traceback # Hata ayıklama için
from datetime import datetime

# --- Genel Ayarlar ---
API_KEY = '9LLhqOMHvNVQs73kG0XKLUbK2xsk0cEzTE36kj0qD8UDaSFYrozQUd70C3Kg6wBA'
API_SECRET = '2rEoRbQwt4xjb1MR1OjZqATNVoSwOntXb0oRYffFWmPR3jGPlUNsstdOmhFgWnyS'
LEVERAGE = 3

COINS_TO_TRADE_CONFIG = [
    {'symbol': 'XRP/USDT', 'collateral_usdt': 5.0, 'trade_sides': 'long_only'},
    {'symbol': 'TRX/USDT', 'collateral_usdt': 5.0, 'trade_sides': 'short_only'},
]

positions_data = {}

exchange = ccxtpro.binance({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'options': {
        'defaultType': 'future',
    },
    'enableRateLimit': True,
})

async def set_leverage_for_symbol(symbol, leverage):
    try:
        # Pozisyon varken kaldıraç/margin modu değişikliği riskli olabilir veya borsada kısıtlı olabilir.
        # Bu fonksiyon idealde bot ilk başladığında veya pozisyon yokken çağrılmalı.
        # Şimdilik mevcut mantığı koruyoruz.
        # current_positions = await exchange.fetch_positions([symbol]) # Bu kontrol kaldıracın ayarlanmasını engelleyebilir.
        # ... (önceki kaldıraç ayarlama mantığınız) ...

        await exchange.set_leverage(leverage, symbol)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için kaldıraç {leverage}x olarak ayarlandı.")
        return True
    except ccxt.MarginModeAlreadySet as e_margin_mode:
        try:
            await exchange.set_leverage(leverage, symbol) # Tekrar dene
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için kaldıraç {leverage}x olarak ayarlandı (margin modu mevcut).")
            return True
        except Exception as e_set_leverage_again:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için kaldıraç (margin modu mevcutken) ayarlanamadı: {e_set_leverage_again}")
    except ccxt.ExchangeError as e_ex:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için kaldıraç ayarlarken BORSA HATASI: {e_ex}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için kaldıraç ayarlarken bilinmeyen genel hata: {e}")
    return False

# DÜZELTİLMİŞ ve SADELEŞTİRİLMİŞ get_current_position_info
async def get_current_position_info(symbol_to_check):
    # print(f"DEBUG: {symbol_to_check} için pozisyon bilgisi alma denemesi...")
    try:
        # Sadece ilgili sembol için pozisyonları çek
        fetched_positions_list = await exchange.fetch_positions([symbol_to_check])
        # print(f"DEBUG: {symbol_to_check} için ham `Workspace_positions` yanıtı: {fetched_positions_list}")

        if not fetched_positions_list:
            # print(f"DEBUG: `Workspace_positions` {symbol_to_check} için boş liste döndürdü.")
            return None

        # Normalde fetch_positions([symbol]) tek bir sembol için ya boş liste ya da tek elemanlı liste döndürür.
        for p_raw in fetched_positions_list:
            if p_raw.get('symbol') == symbol_to_check+":USDT": # Düzeltilmiş sembol karşılaştırması
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
                                except ValueError: pass # info.entryPrice float değilse
                            
                            if final_entry_price == 0.0: # info.entryPrice geçersizse unified'a bak
                                entry_price_unified = p_raw.get('entryPrice')
                                if entry_price_unified is not None:
                                    try:
                                        final_entry_price = float(entry_price_unified)
                                        if final_entry_price <= 0: final_entry_price = 0.0
                                    except ValueError: final_entry_price = 0.0
                        # else: positionAmt "0" ise pozisyon yok kabul edilir
                    except ValueError:
                        print(f"UYARI: {symbol_to_check} için info.positionAmt ({position_amt_str}) float'a çevrilemedi.")
                
                condition_met = final_contracts > 0 and final_side and final_entry_price > 0
                # print(f"DEBUG: {symbol_to_check} Nihai Değerler -> Miktar: {final_contracts}, Yön: {final_side}, Giriş Fiyatı: {final_entry_price}. Koşul ({'GEÇTİ' if condition_met else 'KALDI'})")

                if condition_met:
                    # print(f"DEBUG: {symbol_to_check} için pozisyon bulundu: Miktar={final_contracts}, Yön={final_side}, Giriş Fiyatı={final_entry_price}")
                    return {'quantity': final_contracts, 'side': final_side, 'entry_price': final_entry_price}
        
        # print(f"DEBUG: {symbol_to_check} için tüm p_raw objeleri işlendi, geçerli açık pozisyon bulunamadı.")
        return None # Döngü bitti ve eşleşen/geçerli pozisyon bulunamadı
    except Exception as e:
        print(f"HATA: {symbol_to_check} için `get_current_position_info` içinde istisna: {e}")
        traceback.print_exc()
        return {'error': str(e)}

async def place_order_and_update_state(symbol, side, collateral_for_trade, current_market_price, coin_side_data):
    action = "UZUN" if side == 'buy' else "KISA"
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if current_market_price <= 0:
        print(f"[{timestamp}] {symbol} ({action}) için geçersiz piyasa fiyatı ({current_market_price}), emir verilemiyor.")
        return False

    notional_value_usdt = collateral_for_trade * LEVERAGE
    order_quantity_raw = notional_value_usdt / current_market_price
    
    try:
        order_quantity = float(exchange.amount_to_precision(symbol, order_quantity_raw))
    except Exception as e_prec:
        print(f"[{timestamp}] {symbol} için miktar hassasiyeti ayarlanırken hata: {e_prec}. Ham miktar: {order_quantity_raw}")
        return False

    market_info = exchange.markets[symbol]
    min_amount_limit = market_info.get('limits', {}).get('amount', {}).get('min')
    min_cost_limit = market_info.get('limits', {}).get('cost', {}).get('min')

    if min_amount_limit is not None and order_quantity < min_amount_limit:
        print(f"[{timestamp}] {symbol} ({action}) için hesaplanan miktar ({order_quantity}) minimum ({min_amount_limit}) altında. Emir verilmiyor.")
        return False
    if min_cost_limit is not None and notional_value_usdt < min_cost_limit:
        print(f"[{timestamp}] {symbol} ({action}) için hesaplanan notional değer ({notional_value_usdt:.2f} USDT) minimum ({min_cost_limit} USDT) altında. Emir verilmiyor.")
        return False
    if order_quantity <= 0:
        print(f"[{timestamp}] {symbol} ({action}) için hesaplanan miktar sıfır veya negatif ({order_quantity}). Emir verilmiyor.")
        return False

    print(f"[{timestamp}] {symbol} için {collateral_for_trade:.2f} USDT teminat, {LEVERAGE}x kaldıraç ile ~{order_quantity:.8f} {market_info.get('base','COIN')} miktarında {action} pozisyon girilmeye çalışılıyor (Piyasa Fiyatı: {current_market_price})...")
    
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
            if updated_position_info['side'] == expected_side: # Teyit için
                filled_price = updated_position_info['entry_price']
        
        if filled_price == 0.0 and created_order: 
             if created_order.get('average') and created_order['average'] > 0:
                filled_price = float(created_order['average'])
             elif created_order.get('price') and created_order['price'] > 0:
                filled_price = float(created_order['price'])
             elif created_order.get('filled') and created_order.get('cost') and created_order['filled'] > 0: # Dolan miktar ve maliyetten ortalama fiyat
                filled_price = float(created_order['cost']) / float(created_order['filled'])


        if filled_price > 0:
            coin_side_data['in_position'] = True
            coin_side_data['current_position_actual_entry_price'] = filled_price
            print(f"[{timestamp}] {symbol} için {action} pozisyona girildi. Gerçekleşen Giriş Fiyatı: {filled_price:.4f}")
            if coin_side_data['first_trade_actual_entry_price'] is None:
                coin_side_data['first_trade_actual_entry_price'] = filled_price
                print(f"[{timestamp}] {symbol} ({action}) için bu ilk işlem. Referans giriş fiyatı {filled_price:.4f} olarak ayarlandı.")
            return True
        else:
            print(f"[{timestamp}] {symbol} ({action}) için emir verildi ancak dolum fiyatı/pozisyon teyidi alınamadı. Emir ID: {created_order.get('id') if created_order else 'N/A'}")
            return False
    except ccxt.InsufficientFunds as e:
        print(f"[{timestamp}] {symbol} ({action}) pozisyonuna girerken YETERSİZ BAKİYE: {e}")
    except ccxt.NetworkError as e:
        print(f"[{timestamp}] {symbol} ({action}) pozisyonuna girerken AĞ HATASI: {e}")
    except ccxt.ExchangeError as e:
        print(f"[{timestamp}] {symbol} ({action}) pozisyonuna girerken BORSA HATASI: {e} (Miktar: {order_quantity})")
    except Exception as e:
        print(f"[{timestamp}] {symbol} ({action}) pozisyonuna girerken BİLİNMEYEN HATA: {e}")
        traceback.print_exc()
    return False

async def close_order_and_update_state(symbol, side_to_close, coin_side_data):
    action = "UZUN" if side_to_close == 'long' else "KISA"
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {symbol} için {action} pozisyon ({coin_side_data['current_position_actual_entry_price']}) kapatılmaya çalışılıyor...")

    position_info = await get_current_position_info(symbol)

    if position_info and not position_info.get('error') and position_info['side'] == side_to_close:
        quantity_to_close = position_info['quantity']
        try:
            quantity_to_close_formatted = float(exchange.amount_to_precision(symbol, quantity_to_close))
        except Exception as e_prec_close:
            print(f"[{timestamp}] Kapatma miktarını formatlarken hata {symbol}: {e_prec_close}. Ham miktar: {quantity_to_close}")
            return False

        if quantity_to_close_formatted <= 0:
            print(f"[{timestamp}] {symbol} ({action}) kapatılacak pozisyon miktarı sıfır. Pozisyon zaten kapalı olabilir.")
            coin_side_data['in_position'] = False
            return True

        print(f"[{timestamp}] {symbol} ({action}) kapatılacak miktar: {quantity_to_close_formatted}")
        try:
            if side_to_close == 'long':
                await exchange.create_market_sell_order(symbol, quantity_to_close_formatted, {'reduceOnly': True})
            else: 
                await exchange.create_market_buy_order(symbol, quantity_to_close_formatted, {'reduceOnly': True})
            
            coin_side_data['in_position'] = False
            print(f"[{timestamp}] {symbol} için {action} pozisyon kapatma emri verildi.")
            return True
        except ccxt.ExchangeError as e:
            if "reduceonly" in str(e).lower() or "position side does not match" in str(e).lower() or "order would not reduce position size" in str(e).lower():
                print(f"[{timestamp}] {symbol} ({action}) pozisyonu kapatılırken borsa hatası (muhtemelen zaten kapalı): {e}. Durum güncelleniyor.")
                coin_side_data['in_position'] = False 
                return True 
            print(f"[{timestamp}] {symbol} ({action}) pozisyonunu kapatırken BORSA HATASI: {e}")
        except Exception as e:
            print(f"[{timestamp}] {symbol} ({action}) pozisyonunu kapatırken BİLİNMEYEN HATA: {e}")
            traceback.print_exc()
        return False
    elif position_info and position_info.get('error'):
        print(f"[{timestamp}] {symbol} ({action}) pozisyonu kapatılamadı, pozisyon bilgisi alınırken hata: {position_info.get('error')}")
        return False
    else:
        # Bu log, position_info None ise veya side eşleşmiyorsa tetiklenir.
        # get_current_position_info None döndürdüyse, pozisyon API'dan gelmemiştir.
        print(f"[{timestamp}] {symbol} ({action}) kapatılacak aktif pozisyon bulunamadı veya yön eşleşmiyor (API yanıtı: {position_info}).")
        coin_side_data['in_position'] = False 
        return True

# --- Her Bir Coin İçin Ticaret Mantığı (Güncellendi) ---
async def trade_coin_logic(symbol_config):
    symbol = symbol_config['symbol']
    coin_data = positions_data[symbol]
    
    trade_sides_preference = symbol_config.get('trade_sides', 'both').lower()
    
    # Başlangıç logu için zaman damgası
    start_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{start_timestamp}] {symbol} için ticaret mantığı başlatılıyor. Teminat: {coin_data['long']['collateral_usdt']:.2f} USDT, İşlem Yönleri: {trade_sides_preference.upper()}")
    
    await set_leverage_for_symbol(symbol, LEVERAGE)

    while True:
        try:
            ticker = await exchange.watch_ticker(symbol)
            last_known_price = float(ticker['last'])
            current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # <<< İSTENEN ÖZELLİK: Her döngüde coin ve fiyat verisini ekrana basma >>>
            # Aktif pozisyonların durumunu da ekleyelim
            long_status = "AKTİF" if coin_data['long']['in_position'] else "DEĞİL"
            short_status = "AKTİF" if coin_data['short']['in_position'] else "DEĞİL"
            print(f"[{current_timestamp}] {symbol}: Fiyat={last_known_price:.4f} | Long Poz: {long_status} (Giriş: {coin_data['long']['current_position_actual_entry_price'] if coin_data['long']['in_position'] else 'N/A'}) | Short Poz: {short_status} (Giriş: {coin_data['short']['current_position_actual_entry_price'] if coin_data['short']['in_position'] else 'N/A'})")
            # <<< BİTTİ >>>

            if not last_known_price or last_known_price <= 0:
                await asyncio.sleep(1)
                continue

            # --- LONG POZİSYON MANTIĞI ---
            if trade_sides_preference in ['both', 'long_only']:
                long_data = coin_data['long']
                long_entry_target = long_data['first_trade_actual_entry_price'] if long_data['first_trade_actual_entry_price'] is not None else long_data['initial_target_price']

                if not long_data['in_position']:
                    if last_known_price > long_entry_target:
                        print(f"[{current_timestamp}] LONG GİRİŞ SİNYALİ: {symbol} Fyt({last_known_price:.4f}) > Hdf({long_entry_target:.4f})")
                        await place_order_and_update_state(symbol, 'buy', long_data['collateral_usdt'], last_known_price, long_data)
                        # time.sleep(2) # asyncio içinde time.sleep KULLANILMAMALIDIR! await asyncio.sleep(2) olmalı.
                        # Emir sonrası bekleme gerekiyorsa, place_order_and_update_state içinde zaten var.
                elif long_data['in_position'] and last_known_price < long_data['current_position_actual_entry_price']:
                    print(f"[{current_timestamp}] LONG ÇIKIŞ SİNYALİ: {symbol} Fyt({last_known_price:.4f}) < Grş({long_data['current_position_actual_entry_price']:.4f})")
                    await close_order_and_update_state(symbol, 'long', long_data)

            # --- SHORT POZİSYON MANTIĞI ---
            if trade_sides_preference in ['both', 'short_only']:
                short_data = coin_data['short']
                short_entry_target = short_data['first_trade_actual_entry_price'] if short_data['first_trade_actual_entry_price'] is not None else short_data['initial_target_price']
            
                if not short_data['in_position']:
                    if last_known_price < short_entry_target:
                        print(f"[{current_timestamp}] SHORT GİRİŞ SİNYALİ: {symbol} Fyt({last_known_price:.4f}) < Hdf({short_entry_target:.4f})")
                        await place_order_and_update_state(symbol, 'sell', short_data['collateral_usdt'], last_known_price, short_data)
                elif short_data['in_position'] and last_known_price > short_data['current_position_actual_entry_price']:
                    print(f"[{current_timestamp}] SHORT ÇIKIŞ SİNYALİ: {symbol} Fyt({last_known_price:.4f}) > Grş({short_data['current_position_actual_entry_price']:.4f})")
                    await close_order_and_update_state(symbol, 'short', short_data)
            
            await asyncio.sleep(max(0.3, exchange.rateLimit / 1000 if exchange.rateLimit and exchange.rateLimit > 0 else 0.5))

        except ccxt.NetworkError as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için WebSocket bağlantı hatası: {e}. Yeniden bağlanmaya çalışılacak...")
            await asyncio.sleep(5)
        except ccxt.ExchangeError as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için işlem döngüsünde borsa hatası: {e}")
            if any(err_msg in str(e).lower() for err_msg in ['api key', 'invalid key', 'authentication']):
                 print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için API anahtarı/yetkilendirme sorunu. Bu coin için işlem durduruluyor.")
                 return 
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} için fiyat izleyicide BEKLENMEDİK HATA: {e}")
            traceback.print_exc()
            await asyncio.sleep(10)

async def main():
    global exchange, positions_data
    for coin_conf in COINS_TO_TRADE_CONFIG:
        symbol = coin_conf['symbol']
        collateral = coin_conf['collateral_usdt']
        positions_data[symbol] = {
            'long': { 'in_position': False, 'current_position_actual_entry_price': 0.0, 'first_trade_actual_entry_price': None, 'collateral_usdt': collateral, 'initial_target_price': 0.0 },
            'short': { 'in_position': False, 'current_position_actual_entry_price': 0.0, 'first_trade_actual_entry_price': None, 'collateral_usdt': collateral, 'initial_target_price': float('inf') }
        }
    
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Piyasalar yükleniyor...")
        await exchange.load_markets()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Piyasalar yüklendi.")
        
        tasks = []
        for coin_config_item in COINS_TO_TRADE_CONFIG:
            tasks.append(trade_coin_logic(coin_config_item))
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {len(tasks)} adet coin için ticaret görevleri başlatılıyor...")
        await asyncio.gather(*tasks)

    except Exception as e_main:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ana programda HATA: {e_main}")
        traceback.print_exc()
    finally:
        if exchange and hasattr(exchange, 'close') and getattr(exchange, 'is_open', True): # is_open ccxt.pro'da olmayabilir, True varsayalım
            try:
                await exchange.close()
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exchange bağlantısı kapatıldı.")
            except Exception as e_close:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exchange bağlantısını kapatırken hata: {e_close}")

if __name__ == '__main__':
    print(f"Ticaret botu başlatılıyor... Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"İşlem yapılacak coinler ve ayarları: {COINS_TO_TRADE_CONFIG}")
    print(f"Kullanılacak kaldıraç: {LEVERAGE}x")

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Program kullanıcı tarafından sonlandırıldı (KeyboardInterrupt).")
    except Exception as e_global:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Program genel bir hatayla sonlandı: {e_global}")
        traceback.print_exc()
    finally:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Asyncio event loop ve kaynaklar temizleniyor...")
        if loop.is_running(): # Sadece çalışan loop için görevleri iptal et
            active_tasks = [task for task in asyncio.all_tasks(loop=loop) if not task.done()]
            if active_tasks:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {len(active_tasks)} adet aktif görev iptal ediliyor...")
                for task in active_tasks:
                    task.cancel()
                try:
                    loop.run_until_complete(asyncio.gather(*active_tasks, return_exceptions=True))
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Aktif görevler iptal edildi veya tamamlandı.")
                except asyncio.CancelledError:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Görev iptalleri sırasında CancelledError (beklenen durum).")
                except Exception as e_task_cancel:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Görevleri iptal ederken hata: {e_task_cancel}")
        
        # Exchange bağlantısını (tekrar) kapatmayı dene
        if exchange and hasattr(exchange, 'close') and getattr(exchange, 'is_open', True):
            try:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exchange bağlantısı (finally) kapatılıyor...")
                # loop.is_running() ise ve kapanmamışsa close() dene, yoksa zaten kapanmıştır veya hiç açılmamıştır
                if loop.is_running() or not loop.is_closed(): # Loop kapalı değilse çalıştırmayı deneyebiliriz
                    try:
                        loop.run_until_complete(exchange.close())
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exchange bağlantısı (finally) başarıyla kapatıldı.")
                    except RuntimeError as e_loop_close_run: # Örn: "Event loop is closed"
                         if "event loop is closed" not in str(e_loop_close_run).lower():
                              print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exchange.close() çalıştırılırken Runtime Hata: {e_loop_close_run}")
                         else: # Loop zaten kapalıysa, sorun yok
                              print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exchange.close() çağrılmadı, loop zaten kapalı.")

            except Exception as e_final_close:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exchange bağlantısını (finally) kapatırken genel hata: {e_final_close}")

        # Asenkron jeneratörleri kapat
        try:
            # Sadece çalışan ve kapanmamış loop için
            if loop.is_running() and not loop.is_closed():
                 loop.run_until_complete(loop.shutdown_asyncgens())
                 print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Asyncio async jeneratörleri kapatıldı.")
        except RuntimeError as e_shutdown_gens:
             if "event loop is closed" not in str(e_shutdown_gens).lower() and \
                "cannot schedule new futures after shutdown" not in str(e_shutdown_gens).lower():
                  print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Async jeneratörleri kapatırken Runtime Hata: {e_shutdown_gens}")
        except Exception as e_gens:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Async jeneratörleri kapatırken genel hata: {e_gens}")

        if not loop.is_closed():
            try:
                loop.close()
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Asyncio event loop başarıyla kapatıldı.")
            except Exception as e_loop_close:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Asyncio event loop kapatılırken hata: {e_loop_close}")
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Asyncio event loop zaten kapalıydı.")