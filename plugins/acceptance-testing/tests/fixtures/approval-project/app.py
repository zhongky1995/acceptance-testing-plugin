"""Deliberately imperfect sample for acceptance testing, not production code."""


def create_request(requester, amount):
    if type(amount) is not int or not 1 <= amount <= 10000:
        raise ValueError("amount out of range")
    return {"requester": requester, "amount": amount, "state": "submitted", "approvals": []}


def approve(request, actor, role):
    if role != "manager":
        raise PermissionError("manager required")
    if request["state"] == "approved":
        return request
    request["state"] = "approved"
    request["approvals"].append(actor)
    return request
