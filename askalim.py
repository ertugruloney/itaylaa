import ccxt.async_support as ccxt_async # ccxt.pro yerine async_support kullandık
import asyncio
import traceback
from datetime import datetime # Zaman damgaları için

# --- API Anahtarlarınızı Buraya Girin ---
API_KEY = '9LLhqOMHvNVQs73kG0XKLUbK2xsk0cEzTE36kj0qD8UDaSFYrozQUd70C3Kg6wBA' # Gerçek anahtarlarınızla değiştirin
API_SECRET = '2rEoRbQwt4xjb1MR1OjZqATNVoSwOntXb0oRYffFWmPR3jGPlUNsstdOmhFgWnyS' # Gerçek anahtarlarınızla değiştirin

async def view_all_open_positions():
    exchange = ccxt_async.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'options': {
            'defaultType': 'future',
        },
        'enableRateLimit': True,
    })

    print("Binance Futures'a bağlanılıyor ve açık pozisyonlar sorgulanıyor...")
    try:
        # Piyasaları yüklemek, sembollerle ilgili doğru bilgilere erişim için faydalı olabilir.
        # print("Piyasalar yükleniyor...")
        # await exchange.load_markets() 
        # print("Piyasalar yüklendi.")
        
        # Parametresiz fetch_positions() tüm açık pozisyonları getirmelidir.
        # Belirli bir sembol için: positions = await exchange.fetch_positions(['XRP/USDT'])
        print("Pozisyonlar sorgulanıyor...")
        positions = await exchange.fetch_positions() 

        if not positions:
            print("API'dan herhangi bir pozisyon bilgisi dönmedi veya pozisyon listesi boş.")
            await exchange.close()
            return

        print(f"\n--- API'dan Dönen Ham Pozisyon Kayıtları (Toplam {len(positions)} adet) ---")
        # İsterseniz tüm ham yanıtı görmek için:
        # for i, p_raw_data in enumerate(positions):
        # print(f"Kayıt {i+1}: {p_raw_data}")


        open_positions_found = 0
        print("\n--- Detaylı Pozisyon Analizi ---")
        for p in positions:
            symbol = p.get('symbol', 'N/A')
            
            # Binance'e özgü 'info' alanından direkt veri alalım (genellikle en güvenilir)
            info = p.get('info', {})
            position_amt_info_str = info.get('positionAmt', '0') # Miktar, long için pozitif, short için negatif
            entry_price_info_str = info.get('entryPrice', '0')
            leverage_info_str = info.get('leverage', 'N/A') # Kaldıraç
            unrealized_pnl_info_str = info.get('unRealizedProfit', '0')
            isolated_margin_info_str = info.get('isolatedMargin', 'N/A') # İzole marjin miktarı (eğer izoleyse)
            margin_type_info = info.get('marginType', 'N/A') # 'cross' veya 'isolated'
            update_time_ms = info.get('updateTime', 0)

            # CCXT'nin birleştirdiği (unified) alanlar
            contracts_unified = p.get('contracts') # Genellikle pozitif miktar
            side_unified = p.get('side') # 'long' veya 'short'
            entry_price_unified = p.get('entryPrice')
            
            is_open_based_on_info = False
            calculated_side_from_info = None
            actual_contracts_from_info = 0.0
            
            if position_amt_info_str and float(position_amt_info_str) != 0:
                is_open_based_on_info = True
                actual_contracts_from_info = abs(float(position_amt_info_str))
                if float(position_amt_info_str) > 0:
                    calculated_side_from_info = 'long'
                else:
                    calculated_side_from_info = 'short'
            
            # Sadece gerçekten açık olduğunu düşündüğümüz pozisyonları detaylı yazdıralım
            if is_open_based_on_info:
                open_positions_found += 1
                print("\n-----------------------------------------")
                print(f"AKTİF POZİSYON: {symbol}")
                print(f"  BİNANCE 'INFO' ALANINDAN:")
                print(f"    positionAmt (Miktar): {position_amt_info_str} ({calculated_side_from_info})")
                print(f"    entryPrice (Giriş Fiyatı): {entry_price_info_str}")
                print(f"    leverage (Kaldıraç): {leverage_info_str}")
                print(f"    marginType: {margin_type_info}")
                print(f"    isolatedMargin (İzole Marjin): {isolated_margin_info_str}")
                print(f"    unRealizedProfit (PnL): {unrealized_pnl_info_str}")
                if update_time_ms > 0:
                    print(f"    updateTime: {datetime.fromtimestamp(int(update_time_ms)/1000)}")
                
                print(f"  CCXT BİRLEŞİK ALANLARI (Kontrol Amaçlı):")
                print(f"    contracts: {contracts_unified}")
                print(f"    side: {side_unified}")
                print(f"    entryPrice: {entry_price_unified}")
                print("-----------------------------------------")
            # Tüm kayıtları (miktarı sıfır olanlar dahil) görmek isterseniz aşağıdaki else bloğunu açabilirsiniz
            # else:
            #     print(f"\n--- Kayıt (Miktar Sıfır veya Belirsiz): {symbol} ---")
            #     print(f"  INFO -> positionAmt: {position_amt_info_str}, entryPrice: {entry_price_info_str}")
            #     print(f"  CCXT -> contracts: {contracts_unified}, side: {side_unified}, entryPrice: {entry_price_unified}")


        if open_positions_found == 0:
            print("\nSorgulama sonucunda Binance 'info.positionAmt' değeri sıfırdan farklı olan aktif açık pozisyon bulunamadı.")
        else:
            print(f"\nToplam {open_positions_found} adet 'info.positionAmt' değeri sıfırdan farklı pozisyon bulundu ve listelendi.")

    except ccxt_async.NetworkError as e:
        print(f"Ağ Hatası: {e}")
        traceback.print_exc()
    except ccxt_async.ExchangeError as e:
        print(f"Borsa Hatası: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"Bilinmeyen bir hata oluştu: {e}")
        traceback.print_exc()
    finally:
        if 'exchange' in locals() and exchange: # exchange objesi oluşturulduysa kapat
            await exchange.close()
            print("\nExchange bağlantısı kapatıldı.")

if __name__ == '__main__':
    print("Bu script, Binance Futures hesabınızdaki TÜM açık pozisyonları listeler.")
    print("Lütfen API anahtarlarınızı (API_KEY, API_SECRET) kod içinde doğru girdiğinizden emin olun.")
    print("Script çalıştıktan sonra, özellikle XRP/USDT pozisyonunuzun listelenip listelenmediğini ve detaylarını kontrol edin.\n")
    asyncio.run(view_all_open_positions())