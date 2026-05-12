"""One-shot script to update treasury credentials in .env"""
import re

ENV_PATH = "/opt/telegram-bot/pal-distributor-bot/.env"

NEW_MNEMONIC = "waste canal popular glad wagon rack inner place crumble aerobic injury magnet sand curtain afraid add decade spring file abstract twenty wink brisk innocent"
NEW_ADDRESS = "UQAREqUauMgIPqf6C5MkrZZACPJz3kuSl2FavQ1Djj55FdOn"

with open(ENV_PATH) as f:
    lines = f.readlines()

seen_jetton = False
out = []
for line in lines:
    if line.startswith("TREASURY_MNEMONIC="):
        out.append(f"TREASURY_MNEMONIC={NEW_MNEMONIC}\n")
    elif line.startswith("TREASURY_ADDRESS="):
        out.append(f"TREASURY_ADDRESS={NEW_ADDRESS}\n")
    elif line.startswith("JETTON_MASTER_ADDRESS="):
        if not seen_jetton:
            out.append(line)
            seen_jetton = True
        # skip duplicate
    else:
        out.append(line)

with open(ENV_PATH, "w") as f:
    f.writelines(out)

print("Done. New .env:")
with open(ENV_PATH) as f:
    print(f.read())
