"""Wordlist loader with embedded fallback for the challenge modal."""

from __future__ import annotations

from pathlib import Path


_FALLBACK_WORDS = (
    "about above across action active actual adopt after again agent agree "
    "ahead alarm alert alike alive allow alone along alpha alter among anger "
    "angle angry apart apple apply argue arise arrow aside audio avoid awake "
    "award aware basic basin batch beach bench black blade blame blank blast "
    "bleed blend bless blind blink block blood bloom blown board boost booth "
    "bound brain brake brand brave bread break brick brief bring broad broke "
    "brown brush build built bunch burst buyer cabin cable candy carry catch "
    "chain chair chalk charm chart chase check cheer chess chest chief child "
    "civil claim class clean clear clerk click cliff climb clock close cloth "
    "cloud coach coast color cover craft crash cream creek crest crime crisp "
    "cross crowd crown crude cruel crush cycle daily dance death debit debut "
    "delay delta demon dense depth dirty diver dizzy dough dozen drain drama "
    "dream dress drink drive drove drown drunk eagle early earth eaten echo "
    "eight elbow elder elect empty enemy enjoy enter entry equal error event "
    "every exact exist extra fable faint faith false fancy fatal fault favor "
    "fence ferry fetch fever fiber field fifth fifty fight final first fixed "
    "flame flash fleet flesh flint float flock flood floor flour flute focus "
    "force forge forth forty forum found frame fraud fresh front frost fruit "
    "funny ghost giant given glare glass gleam glide globe gloom glory glove "
    "going grace grade grain grand grant grape graph grasp grass grave great "
    "greed green greet grief grill grind gross group grown grunt guard guess "
    "guest guide guild habit happy heart heavy hedge hello hover human humor "
    "hurry ideal image index inner input issue ivory jelly jewel joint juice "
    "kayak knack knife knock known label large laser later laugh lazy learn "
    "least leave legal lemon level light limit linen liver lobby local logic "
    "loose loyal lunar lunch magic major maple march match maybe mayor medal "
    "media metal meter might minor mixed model moist money month moral mount "
    "mouse mouth movie nasty nerve never night noble noise north novel ocean "
    "offer often olive onion opera orbit order ought ounce outer owner paint "
    "panel panic paper party patch peace pearl penny phase photo piano piece "
    "pilot pizza plane plant plate plaza poem point polar porch pouch pound "
    "power press price pride prime print prior prize proof proud pulse punch "
    "purse quart queen quest queue quick quiet quilt quirk quite quote radar "
    "radio rapid ratio reach react ready realm relay reply reset resin ridge "
    "rigid rinse rival river roast rocky rough round royal rusty sadly salad "
    "sandy sauce scale scarf scene scent scout scrap scrub seven shake shall "
    "shape share sharp sheep sheet shelf shell shift shine shiny shirt shock "
    "short shout shown shrub sight silly since sixth skate skill slate sleep "
    "slept slice slide slope small smart smell smile smoke smoky snack snake "
    "snore snowy solid solve sorry sound south spade spare spark speak speed "
    "spell spend spent spice spike spine spoke spoon sport spray stack staff "
    "stage stair stamp stand stark state steam steel steep stern stick still "
    "sting stock stone stool storm story stove straw strip stuck study stuff "
    "style sugar sweep sweet swift swing table tally taste teach teeth tempo "
    "tenor tense thank theft their theme there thick thief thigh thing think "
    "third thorn those three threw throw thumb tidal tight tiger timer tired "
    "toast today token tooth topic torch total touch tough tower toxic trace "
    "track trade trail train trait trash treat trend trial tribe trick tried "
    "troop trout truck truly trunk trust truth tulip tutor twice twist ultra "
    "uncle under unite unity until upper upset urban usage usual vague valid "
    "value vapor vault verge verse video viola vital vivid vocal voice vowel "
    "wagon waltz water waver wedge weigh weird whale wharf wheat wheel whirl "
    "white whole wider witch woven wrist write wrong yacht yeast yield young "
    "youth zebra"
).split()


def load_wordlist() -> tuple[list[str], str]:
    """Return (words, source_description). Tries words.txt next to the script
    and in cwd; otherwise returns the embedded fallback.
    """
    candidates = [
        Path(__file__).resolve().parent / "words.txt",
        Path.cwd() / "words.txt",
    ]
    for p in candidates:
        try:
            text = p.read_text()
        except OSError:
            continue
        words = [w.strip().lower() for w in text.splitlines() if w.strip()]
        if len(words) >= 50:
            return words, f"file: {p}"
    return list(_FALLBACK_WORDS), f"embedded ({len(_FALLBACK_WORDS)} words)"
