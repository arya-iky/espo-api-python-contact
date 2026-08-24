import requests
from requests.auth import HTTPBasicAuth

url = "http://localhost:8081/api/v1/Contact"

response = requests.get(
    url,
    auth=HTTPBasicAuth("admin", "admin123")
)

response.raise_for_status()

data = response.json()

print("=" * 50)
print("      DATA CONTACT ESPOCRM")
print("=" * 50)
print(f"Jumlah Contact : {data['total']}")
print()

for i, contact in enumerate(data["list"], start=1):
    print(f"Contact #{i}")
    print(f"Nama   : {contact['name']}")
    print(f"Email  : {contact['emailAddress']}")
    print(f"Telepon: {contact['phoneNumber']}")
    print("-" * 50)