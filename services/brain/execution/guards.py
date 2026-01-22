def validate_order(order: dict):
    required = ["symbol", "side", "qty"]

    for key in required:
        if key not in order:
            raise ValueError(f"Missing {key}")

    if order["qty"] <= 0:
        raise ValueError("Invalid quantity")

    return True
