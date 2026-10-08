import json
import sys

import _boot

from app.agent.parse import parse_message

CASES = [
    "Ajke lunch 350 taka khoroch hoise",
    "Lunch e 350, Uber e 280",
    "arai hajar bazar korlam bkash e",
    "লাঞ্চে ৩৫০ টাকা খরচ হইছে",
    "kal bikale Rahim ke call dite remind koro",
    "Rahim ke call dite remind koro",
    "protidin sokal 8 tay medicine kheye nite hobe",
    "porshu bikale doctor er appointment ache",
    "Bazar list e dim, pyaj, tel add koro",
    "dim ar tel kena hoise",
    "My internet customer ID is 78243",
    "ID koto?",
    "Ei mash e food e koto gelo?",
    "ki ki kinte hobe?",
    "Tanvir bhai 12 tarikh e Dhaka ashbe",
    "undo",
    "asdkjhasd",
    "gotokal cng e 120 dilam",
    "dui hajar 500 taka current bill dilam",
]


async def main() -> None:
    cases = sys.argv[1:] or CASES
    for text in cases:
        res = await parse_message(text, "Asia/Dhaka")
        actions = [a.model_dump(exclude_none=True) for a in res.actions]
        print(f"\n\033[1m{text}\033[0m")
        print(f"  lang={res.lang}")
        for a in actions:
            print("  " + json.dumps(a, ensure_ascii=False))


_boot.run(main())
