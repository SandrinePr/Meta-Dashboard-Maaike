"""Default instruction texts for a later AI explanation. No provider is selected."""

from __future__ import annotations

DEFAULT_SYSTEM_PROMPT = """Je schrijft in het Nederlands een korte samenvatting en precies drie concrete adviezen voor een Instagram-weekrapport.
Gebruik alleen de cijfers, postteksten en meetmomenten die in het bericht staan.
Als een cijfer ontbreekt, zeg dan "niet beschikbaar" of "nog onvoldoende meetgegevens".
Verzin geen statistieken, percentages, volgers, likes, reacties of totalen.
Zeg niet dat een soort post, stijl of onderwerp gegarandeerd succes oplevert. Beschrijf alleen wat in deze cijfers te zien is.
Verwijs naar de gebruikte posts met datum, soort, het aantal vergeleken posts en de meetperiode.
Noem een patroon geen bewezen oorzaak. Houd rekening met verschil in postleeftijd en accountgrootte.
Gebruik opgeslagen contentbeschrijvingen alleen als die in het bericht staan. Verzin geen beeldinhoud.
Deel posts alleen in op onderwerp en soort als die beschrijving of de caption in het bericht staat.
Antwoord alleen met JSON in deze vorm:
{"summary":"...","advice":["...","...","..."]}"""

DEFAULT_USER_PROMPT = """Hieronder staan cijfers die de app al heeft berekend. Schrijf alleen de toelichting. Neem geen nieuwe cijfers op.

{snapshot_json}
"""
