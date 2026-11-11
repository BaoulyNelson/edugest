"""Exceptions métier : leur message est destiné à être affiché tel quel à l'utilisateur."""


class ErreurMetier(Exception):
    """Règle métier violée (message compréhensible par l'utilisateur final)."""
