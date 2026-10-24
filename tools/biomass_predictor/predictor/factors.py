"""Conversion factors, each with low / likely / high, a source and an honest status.

status:
  provided    - given to us by Regenerix, not from a published source
  published   - the number comes straight from the cited source
  derived     - calculated by us from published numbers (the working is in `note`)
  assumption  - our placeholder; NO published source yet. The technical team must confirm
                or replace it before the numbers are used for anything but a rough idea.

Change a number here and everything else (page, API, README table) follows.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    unit: str
    low: float
    likely: float
    high: float
    status: str
    source: str
    url: str
    note: str = ""

    def as_dict(self):
        return dict(self.__dict__)


CSE = "https://cdn.cseindia.org/attachments/0.86053500_1785406558_national-bluepint.pdf"
ICAR = "https://epubs.icar.org.in/index.php/IJAgS/article/download/59001/24421/147276"
MDPI = "https://www.mdpi.com/2071-1050/14/9/5077"
IPCC = "https://greencalculus.com/data/afolu-biomass-burning-factors/"
BEE = "https://www.spglobal.com/energy/en/news-research/latest-news/energy-transition/110124-industry-sees-initial-carbon-credits-priced-around-10mtco2e-in-india"
RAILA = "https://www.tf.lbtu.lv/conference/proceedings2012/Papers/050_Raila_A.pdf"

FACTORS = {
    f.key: f
    for f in [
        Factor(
            "density_round", "Round bale density (as baled)", "kg per m³", 87, 95, 130, "published",
            "ICAR Indian Journal of Agricultural Sciences, round balers, Tamil Nadu", ICAR,
            "The study measured about 87-102 kg/m³. The upper end (130) is our widening for denser balers; "
            "it is an assumption.",
        ),
        Factor(
            "density_rect", "Rectangular bale density (as baled)", "kg per m³", 100, 140, 190, "assumption",
            "No source found yet", "",
            "Placeholder. Needs a source for small and large rectangular straw bales.",
        ),
        Factor(
            "field_t_per_acre", "Loose straw lying in a fully covered field", "tonnes per acre", 1.8, 2.8, 3.5, "derived",
            "MDPI Sustainability 14(9):5077 (residue-to-product ratio 1.7, Punjab rice yield 4,132 kg/ha)", MDPI,
            "1.7 x 4,132 kg/ha = 7.0 t/ha = about 2.8 t/acre of straw. Low and high are our widening. "
            "Based on paddy; wheat and other crops have no source yet.",
        ),
        Factor(
            "moisture_dry", "Straw moisture - looks dry", "fraction of weight", 0.08, 0.12, 0.15, "assumption",
            "No source found yet", "", "Typical air-dry straw; to be confirmed.",
        ),
        Factor(
            "moisture_damp", "Straw moisture - looks damp", "fraction of weight", 0.16, 0.20, 0.25, "published",
            "ICAR study measured straw at 18-21% moisture when baled", ICAR, "Low and high are our widening.",
        ),
        Factor(
            "moisture_wet", "Straw moisture - looks wet", "fraction of weight", 0.25, 0.30, 0.40, "assumption",
            "No source found yet", "", "Rained-on or green straw; to be confirmed.",
        ),
        Factor(
            "cbg_straw_ratio", "Straw needed for 1 tonne of CBG", "tonnes of straw (at 15% moisture)", 8, 10, 14, "published",
            "CSE national blueprint for CBG, 5 tonne-per-day plant model: 10 tonnes of paddy straw per tonne of CBG", CSE,
            "The 10 comes from the source. The report gives no moisture, so we take 15%. Low and high "
            "(8 and 14) are our widening until a second source is found.",
        ),
        Factor(
            "pellet_moisture", "Moisture in finished pellets", "fraction of weight", 0.08, 0.10, 0.12, "assumption",
            "Raila et al. tested pellets between 0.6% and 18.5% moisture", RAILA,
            "10% is our placeholder for sellable pellets.",
        ),
        Factor(
            "pellet_recovery", "Share of dry straw that ends up in pellets", "fraction", 0.85, 0.93, 0.97, "assumption",
            "No source found yet", "", "Allows for dust, screening and process loss.",
        ),
        Factor(
            "clearing_cost", "Cost to the farmer of clearing one acre", "Rs per acre", 2000, 2000, 2000, "provided",
            "Regenerix (told to us by the project owner)", "",
            "Regenerix will not charge this to the farmer, so it is shown as money the farmer saves, not cash received. "
            "Regenerix does not currently pay for the straw.",
        ),
        Factor(
            "carbon_per_dry_tonne", "Emissions avoided by not burning (CH4 + N2O)", "tonnes CO2e per tonne dry straw", 0.05, 0.074, 0.10, "derived",
            "IPCC 2006 Vol.4 Ch.2 (CH4 2.7 g and N2O 0.07 g per kg dry matter burnt; rice combustion factor 0.8), "
            "AR6 warming values 27 and 273", IPCC,
            "0.8 x (2.7 x 27 + 0.07 x 273) / 1000 = 0.074. Low and high are our widening. "
            "A real credit needs a registered method and verification, which may count differently.",
        ),
        Factor(
            "carbon_price", "Carbon credit price", "Rs per tonne CO2e", 600, 850, 1100, "assumption",
            "Indian government expects about US$10 per credit (BEE, quoted by S&P Global, Nov 2024)", BEE,
            "We assumed about Rs 85 per US$; the exchange rate and voluntary-market price are not sourced.",
        ),
    ]
}

CBG_REFERENCE_MOISTURE = 0.15

SIZE_CONFIDENCE_SPREAD = {"high": 0.10, "medium": 0.20, "low": 0.35}
