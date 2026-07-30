import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

# Parametros
NUM_CUSTOMERS = 1000
NUM_TRANSACTIONS = 7000

np.random.seed(42)
random.seed(42)

# Top 3 bancos de consumo por pais
BANKS_BY_COUNTRY = {
    "PE": ["BCP", "BBVA", "IBK"],     # Banco de Credito, BBVA Peru, Interbank
    "US": ["JPM", "BAC", "WFC"],      # Chase, Bank of America, Wells Fargo
    "CO": ["BAN", "DAV", "BOG"],      # Bancolombia, Davivienda, Banco de Bogota
    "ES": ["SAN", "BBVA", "CABK"],    # Santander, BBVA, CaixaBank
    "MX": ["BBVA", "BAN", "SAN"],     # BBVA Mexico, Banorte, Santander
    "AR": ["BNA", "GAL", "SAN"],      # Banco Nacion, Galicia, Santander
    "CL": ["BCH", "SAN", "BCI"]       # Banco de Chile, Santander, BCI
}

def generate_customers():
    countries = ["PE", "US", "CO", "ES", "MX", "AR", "CL"]
    channels = ["web", "mobile"]
    
    customers = []
    
    for i in range(1, NUM_CUSTOMERS + 1):
        c_id = f"CU-{i:03d}"
        avg_amt = round(np.random.uniform(100, 5000), 2)
        
        start_hour = np.random.randint(6, 12)
        end_hour = np.random.randint(18, 23)
        hours = f"{start_hour:02d}-{end_hour:02d}"
        
        country = np.random.choice(countries)
        device = f"D-{i:03d}"
        
        usual_channel = np.random.choice(channels)
        
        is_new = random.random() < 0.1
        if is_new:
            creation_date = datetime(2025, 11, np.random.randint(15, 30))
        else:
            creation_date = datetime(2020 + np.random.randint(0, 5), np.random.randint(1, 13), np.random.randint(1, 28))
            
        last_profile = creation_date + timedelta(days=np.random.randint(0, 100))
        if last_profile.year < 2025:
            last_profile = datetime(2025, 11, np.random.randint(1, 30))
            
        issuer_bank = np.random.choice(BANKS_BY_COUNTRY[country])
        daily_limit = round(avg_amt * np.random.uniform(3, 8), 2)
        
        customers.append({
            "customer_id": c_id,
            "usual_amount_avg": f"{avg_amt:.2f}",
            "usual_hours": hours,
            "usual_countries": country,
            "usual_devices": device,
            "usual_channel": usual_channel,
            "account_creation_date": creation_date.strftime("%Y-%m-%d"),
            "last_profile_update": last_profile.strftime("%Y-%m-%dT%H:%M:%S"),
            "issuer_bank": issuer_bank,
            "daily_limit": f"{daily_limit:.2f}"
        })
    return pd.DataFrame(customers)

def _make_tx(t_id, c_id, amt, country, channel, dev, t_date, merch, bank):
    currency = "PEN" if country == "PE" else "USD"
    return {
        "transaction_id": f"T-{t_id}",
        "customer_id": c_id,
        "amount": f"{amt:.2f}",
        "currency": currency,
        "country": country,
        "chanel": channel,
        "device_id": dev,
        "timestamp": t_date.strftime("%Y-%m-%dT%H:%M:%S"),
        "merchant_id": merch,
        "issuer_bank": bank
    }

def generate_transactions(customers_df):
    transactions = []
    t_id_counter = 1000
    
    merchants = [f"M-{i:03d}" for i in range(1, 51)]
    start_date = datetime(2025, 12, 1)
    
    i = 0
    while i < NUM_TRANSACTIONS:
        t_id_counter += 1
        
        customer = customers_df.iloc[np.random.randint(0, NUM_CUSTOMERS)]
        c_id = customer["customer_id"]
        avg_amt = float(customer["usual_amount_avg"])
        u_hours = customer["usual_hours"]
        u_country = customer["usual_countries"]
        u_device = customer["usual_devices"]
        u_channel = customer["usual_channel"]
        c_date = datetime.strptime(customer["account_creation_date"], "%Y-%m-%d")
        last_profile = datetime.strptime(customer["last_profile_update"], "%Y-%m-%dT%H:%M:%S")
        u_bank = customer["issuer_bank"]
        daily_limit = float(customer["daily_limit"])
        
        start_h, end_h = map(int, u_hours.split("-"))
        
        rand_val = random.random()
        
        if rand_val < 0.01:
            # FP-01: Monto > 3x y fuera horario
            amt = round(avg_amt * np.random.uniform(3.5, 5.0), 2)
            valid_out_hours = [h for h in range(24) if h < start_h or h > end_h]
            if not valid_out_hours:
                valid_out_hours = [3]
            th = np.random.choice(valid_out_hours)
            t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=int(th), minutes=np.random.randint(0, 60))
            transactions.append(_make_tx(t_id_counter, c_id, amt, u_country, u_channel, u_device, t_date, np.random.choice(merchants), u_bank))
            i += 1
            
        elif rand_val < 0.02:
            # FP-02: Int + nuevo device
            amt = round(avg_amt * np.random.uniform(0.5, 1.5), 2)
            th = np.random.randint(start_h, end_h + 1) if start_h <= end_h else 12
            t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=int(th), minutes=np.random.randint(0, 60))
            transactions.append(_make_tx(t_id_counter, c_id, amt, "RU", u_channel, f"D-999{np.random.randint(100,999)}", t_date, np.random.choice(merchants), u_bank))
            i += 1
            
        elif rand_val < 0.03:
            # FP-03: Velocity (4 tx en 4 min)
            t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=12)
            merch = np.random.choice(merchants)
            for j in range(4):
                amt = round(avg_amt * np.random.uniform(0.1, 0.5), 2)
                t_date += timedelta(minutes=1)
                transactions.append(_make_tx(t_id_counter+j, c_id, amt, u_country, u_channel, u_device, t_date, merch, u_bank))
            t_id_counter += 3
            i += 4
            
        elif rand_val < 0.04:
            # FP-04: Card testing (2 x 0.50 y luego 1 grande)
            t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=14)
            dev = f"D-999{np.random.randint(100,999)}"
            for j in range(2):
                transactions.append(_make_tx(t_id_counter+j, c_id, 0.50, u_country, u_channel, dev, t_date + timedelta(minutes=j*2), np.random.choice(merchants), u_bank))
            transactions.append(_make_tx(t_id_counter+2, c_id, round(avg_amt * 4, 2), u_country, u_channel, dev, t_date + timedelta(minutes=6), np.random.choice(merchants), u_bank))
            t_id_counter += 2
            i += 3
            
        elif rand_val < 0.05:
            # FP-05: Geolocalizacion
            t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=10)
            transactions.append(_make_tx(t_id_counter, c_id, avg_amt, 'PE', u_channel, u_device, t_date, np.random.choice(merchants), u_bank))
            transactions.append(_make_tx(t_id_counter+1, c_id, avg_amt, 'ES', u_channel, u_device, t_date + timedelta(hours=1, minutes=30), np.random.choice(merchants), u_bank))
            t_id_counter += 1
            i += 2
            
        elif rand_val < 0.06:
            # FP-06: Canal nuevo con monto alto (> 2x)
            amt = round(avg_amt * np.random.uniform(2.1, 3.5), 2)
            new_channel = "mobile" if u_channel == "web" else "web"
            th = np.random.randint(start_h, end_h + 1) if start_h <= end_h else 12
            t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=int(th))
            transactions.append(_make_tx(t_id_counter, c_id, amt, u_country, new_channel, u_device, t_date, np.random.choice(merchants), u_bank))
            i += 1
            
        elif rand_val < 0.07:
            # FP-07: Merchant en lista negra
            amt = round(np.random.uniform(600, 2000), 2)
            th = np.random.randint(start_h, end_h + 1) if start_h <= end_h else 12
            t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=int(th))
            transactions.append(_make_tx(t_id_counter, c_id, amt, u_country, u_channel, u_device, t_date, "M-999", u_bank))
            i += 1
            
        elif rand_val < 0.08:
            # FP-09: Cuenta nueva (< 30 dias) monto > 5x
            if (datetime(2025,12,31) - c_date).days < 45:
                amt = round(avg_amt * np.random.uniform(5.1, 8.0), 2)
                th = np.random.randint(start_h, end_h + 1) if start_h <= end_h else 12
                t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=int(th))
                transactions.append(_make_tx(t_id_counter, c_id, amt, u_country, u_channel, u_device, t_date, np.random.choice(merchants), u_bank))
            else:
                amt = round(avg_amt * np.random.uniform(0.5, 1.5), 2)
                th = np.random.randint(start_h, end_h + 1) if start_h <= end_h else 12
                t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=int(th))
                transactions.append(_make_tx(t_id_counter, c_id, amt, u_country, u_channel, u_device, t_date, np.random.choice(merchants), u_bank))
            i += 1
            
        elif rand_val < 0.09:
            # FP-10: Cambio perfil + Tx inmediata
            t_date = last_profile + timedelta(minutes=10)
            amt = round(avg_amt * np.random.uniform(0.5, 2.0), 2)
            transactions.append(_make_tx(t_id_counter, c_id, amt, u_country, u_channel, u_device, t_date, np.random.choice(merchants), u_bank))
            i += 1
            
        elif rand_val < 0.10:
            # FP-11: Alerta externa (Simulamos un banco especifico afectado)
            # Aunque asigne el del usuario, en la vida real la alerta externa es sobre un bin particular.
            amt = round(avg_amt * np.random.uniform(0.5, 1.5), 2)
            th = np.random.randint(start_h, end_h + 1) if start_h <= end_h else 12
            t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=int(th))
            transactions.append(_make_tx(t_id_counter, c_id, amt, u_country, u_channel, u_device, t_date, np.random.choice(merchants), u_bank))
            i += 1
            
        elif rand_val < 0.11:
            # FP-12: Smurfing (3 pagos q sumen > daily_limit)
            t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=9)
            merch = np.random.choice(merchants)
            amt = round(daily_limit * 0.4, 2)
            for j in range(3):
                transactions.append(_make_tx(t_id_counter+j, c_id, amt, u_country, u_channel, u_device, t_date + timedelta(hours=j*2), merch, u_bank))
            t_id_counter += 2
            i += 3
            
        else:
            # Normal
            amt = round(avg_amt * np.random.uniform(0.5, 1.5), 2)
            th = np.random.randint(start_h, end_h + 1) if start_h <= end_h else 12
            t_date = start_date + timedelta(days=np.random.randint(0, 30), hours=int(th), minutes=np.random.randint(0, 60))
            transactions.append(_make_tx(t_id_counter, c_id, amt, u_country, u_channel, u_device, t_date, np.random.choice(merchants), u_bank))
            i += 1
            
    return pd.DataFrame(transactions)

if __name__ == "__main__":
    print("Generando clientes con bancos actualizados...")
    df_customers = generate_customers()
    df_customers.to_csv("data/customer_behavior.csv", index=False)
    
    print("Generando transacciones con informacion de bancos...")
    df_transactions = generate_transactions(df_customers)
    df_transactions = df_transactions.sort_values(by="timestamp").reset_index(drop=True)
    df_transactions.to_csv("data/transactions.csv", index=False)
    
    print(f"Generados {len(df_customers)} clientes en 'data/customer_behavior.csv'")
    print(f"Generadas {len(df_transactions)} transacciones en 'data/transactions.csv'")
