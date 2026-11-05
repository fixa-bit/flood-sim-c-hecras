"""Parser cases taken from real 2022 FFC Annexure-I pages."""
from server.observations import parse_ffc_page

HEADER = ("                    1                         2                3                   4                  5"
          "             6                7                8                 9                           10")
PAGE = "\n".join([
    "ANNEXURE-I",
    "   A. River Flow Situation:",
    "                                 August 27, 2022 at 0600 Hours",
    HEADER,
    "       River Indus",
    "        Tarbela Reservoir               1,500,000            604,000        30-7-2010          179,000          154,000           395,000         332,000          Low Flood (F)               650,000",
    "        Guddu                           1,200,000          1,199,672        15-8-1976          161,000          118,000          313,000          292 ,000         Low Flood (R)               700,000",
    "       River Kabul",
    "        Warsak                            540,000                                                                17,000                            130,000        High Flood (R)               200,000",
    "        Nowshera                                             450,000        29-07-2010                           37,000                            42.000             Normal                  200,000",
    "        Rasul                             850,000            952,170        10-9-1992           28,000             12,000            5,000             NIL             Normal                  225,000",
    "   Mangla Reservoir              1,060,000          1,090,000        10-9-1992            43,000    0    18,000           42,000           15,000          Normal",
    "   B. Reservoir Storage Position:",
    "        Marala                          1,100,000          1,100,000        26-8-1957           61,000           26,000             66,000          38,000             Normal",
])


def test_ffc_rows_are_read_from_their_own_columns_and_ambiguities_are_left_out():
    rows, skipped = parse_ffc_page(PAGE)
    values = {(row["station_id"], row["quantity"]): row["discharge_cusecs"] for row in rows}
    assert values == {
        ("tarbela", "inflow"): 395000, ("tarbela", "outflow"): 332000,  # bullet glyph before the name
        ("guddu", "inflow"): 313000, ("guddu", "outflow"): 292000,  # "292 ,000" is one number, never 292
        ("warsak", "outflow"): 130000,  # no inflow printed: none invented
        ("rasul", "inflow"): 5000, ("rasul", "outflow"): 0,  # NIL kept as reported
    }
    assert {row["reported_as"] for row in rows if row["station_id"] == "rasul"} == {"5,000", "NIL"}
    assert all(row["time_local"] == "2022-08-27T06:00:00+05:00" and row["time_utc"] == "2022-08-27T01:00:00+00:00"
               for row in rows)
    reasons = [item["reason"] for item in skipped]
    assert "malformed number '42.000' left out" in reasons  # Nowshera outflow is not corrected
    assert "numbers do not map to distinct, ordered columns" in reasons  # Mangla's stray 0
    assert not any(row["station_id"] in {"nowshera", "mangla", "marala"} for row in rows)  # Marala is below the table


def test_pages_without_the_river_flow_table_are_ignored():
    assert parse_ffc_page("Weather & Rainfall Forecast (Next 24 hours)") == (None, [])
