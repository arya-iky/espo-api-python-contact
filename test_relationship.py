import api

contact_id = "6a77f74bbd558f9c07"

try:
    result = api.get_contact_accounts(
        contact_id=contact_id,
        max_size=20
    )

    print("\n========== HASIL RELATIONSHIP ==========")
    print(result)

    print("\n========== LIST ==========")
    print(result.get("list", []))

    print("\n========== TOTAL ==========")
    print(result.get("total", 0))

except Exception as e:
    print("\n========== ERROR ==========")
    print(e)