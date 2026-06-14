"""
attack_core — wspólny fundament całego ekosystemu ataku.

Cele (`objectives`), wektory wstrzyknięcia (`injection_points`), niezależny sędzia
(`judge`), lifecycle (`runner`), niemodyfikowalne prymitywy (`primitives`) oraz
reużywalny zestaw strategii (`strategies/`). KAŻDY silnik ataku (payload_attack,
hyperagent, hyperagent_email) zależy WYŁĄCZNIE od tego pakietu — żaden silnik nie
importuje z innego silnika.
"""
