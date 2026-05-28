class MT103Service:
    def generate(self, trn: str, amount: float, bic_sender: str, bic_receiver: str) -> str:
        return f"<MT103><TRN>{trn}</TRN><AMOUNT>{amount}</AMOUNT><SENDER>{bic_sender}</SENDER><RECEIVER>{bic_receiver}</RECEIVER></MT103>"
