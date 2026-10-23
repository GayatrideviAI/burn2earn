# Straw to CBG and pellets estimator

A public, stand-alone web tool. Anyone uploads one photo of baled or loose crop straw and gets a
**range** in tonnes of CBG and of pellets. It does not use the Regenerix login or database.

## How it works

1. The visitor picks *Bales or stacks* or *Loose straw in a field*, uploads a photo and says what
   object of known size is in it (A4 paper, a 1 m stick, a door...).
2. The server shrinks the photo, removes location and device details, and sends it to a vision
   model, which only reports what it sees (bale count and size, or field area and cover, and how
   dry the straw looks). The photo is never saved.
3. `predictor/engine.py` does the arithmetic with the numbers in `predictor/factors.py`. The range
   comes from moving each uncertain input to its low and high value and combining the effects in
   quadrature.
4. A visitor who knows the weight of one bale can enter it, which replaces the size and density
   guess.

## Conversion figures and where they come from

Every figure has low / likely / high and a status. **The technical team must confirm these before
the numbers are used for anything but a rough idea.** The live table is also shown on the page.

| Figure | Low / likely / high | Status | Source |
|---|---|---|---|
| Round bale density | 87 / 95 / 130 kg/m³ | published (top end ours) | [ICAR IJAgS](https://epubs.icar.org.in/index.php/IJAgS/article/download/59001/24421/147276), measured 87-102 |
| Rectangular bale density | 100 / 140 / 190 kg/m³ | **assumption** | none yet |
| Loose straw, fully covered field | 1.8 / 2.8 / 3.5 t/acre | derived | [MDPI 14(9):5077](https://www.mdpi.com/2071-1050/14/9/5077): 1.7 x 4,132 kg/ha |
| Moisture: dry / damp / wet | 12% / 20% / 30% | assumption / published (ICAR 18-21%) / assumption | |
| Straw per tonne of CBG | 8 / 10 / 14 t at 15% moisture | 10 published, range ours | [CSE blueprint](https://cdn.cseindia.org/attachments/0.86053500_1785406558_national-bluepint.pdf) |
| Pellet moisture | 8 / 10 / 12% | assumption | context: [Raila et al.](https://www.tf.lbtu.lv/conference/proceedings2012/Papers/050_Raila_A.pdf) |
| Dry straw ending up in pellets | 85 / 93 / 97% | **assumption** | none yet |

Still needed: wheat straw figures, a second CBG yield source (the 10:1 comes from one report), a
pellet recovery source, rectangular bale densities.

## Honest limits

- The vision step has **not been checked against weighed piles**. Once the weight-photo data from
  the Yard and Mitra apps exists, compare predictions with weighbridge weights and tune the ranges.
- One photo cannot see inside a stack. Counting hidden bales is a guess, shown as a low-high count.
- Field mode is far less exact than bale mode.

## Run it

```
cd tools/biomass_predictor
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # never commit this
uvicorn --factory predictor.app:create_app --port 8001
```

Docker: `docker build -t biomass-predictor . && docker run -p 8001:8001 -e ANTHROPIC_API_KEY biomass-predictor`

Settings (environment): `PREDICTOR_MODEL` (default `claude-sonnet-5-5`), `PREDICTOR_PER_IP_HOURLY`
(10), `PREDICTOR_DAILY_TOTAL` (500, caps your vision bill), `PREDICTOR_TRUST_PROXY=1` only behind a
reverse proxy that sets `X-Forwarded-For`.

Limits are kept in memory per process, so run one worker or put a proper limiter in front. Serve it
over HTTPS. Every estimate costs one vision call, so keep the daily cap.

## Tests

```
pip install -r requirements.txt && python -m unittest discover -s tests -t .
```
They use a fake vision reader, so no key or network is needed.
