import base64
import json

def decrypt_captured_payload(b64_text: str, key: str):
    """
    Decrypts an obfuscated payload captured from the browser network tab.
    
    TO GET THE SESSION KEY (APP_SESSION_KEY):
    -----------------------------------------------------
      1. Open Browser Developer Tools (F12) -> Console.
      2. Type `window.APP_SESSION_KEY` and press Enter.
    -----------------------------------------------------
    """
    if not b64_text or not key:
        print("Error: You must provide both the captured payload and the session key.")
        return

    try:
        # Convert key and base64 text to bytes
        key_bytes = key.encode('utf-8')
        text_bytes = base64.b64decode(b64_text)
        
        # XOR decryption
        res = bytearray()
        for i in range(len(text_bytes)):
            res.append(text_bytes[i] ^ key_bytes[i % len(key_bytes)])
            
        decrypted_str = res.decode('utf-8')
        
        # Parse and pretty print the JSON
        parsed_json = json.loads(decrypted_str)
        print("\n--- SUCCESSFULLY DECRYPTED PAYLOAD ---\n")
        print(json.dumps(parsed_json, indent=2))
        print("\n--------------------------------------\n")
        
    except Exception as e:
        print(f"Error decrypting payload: {e}")

if __name__ == "__main__":
    # --- Paste your values here ---
    SESSION_KEY = "eed0cc9477d790685b1949bab5b6022e"
    CAPTURED_PAYLOAD = "HkcQSRMGGw4VUAxoWlxfGhlARVZfXAxDWBcmY31rbTUkNjdnLDF9FhsVEUVVEgwaF04TUVtKFg8DWAcUChBVDBENEVJNDkBXWFoUVldJGFtaDxNE"
    
    if not SESSION_KEY or not CAPTURED_PAYLOAD:
        print("Please edit this script and paste your SESSION_KEY and CAPTURED_PAYLOAD at the bottom.")
    else:
        decrypt_captured_payload(CAPTURED_PAYLOAD, SESSION_KEY)
