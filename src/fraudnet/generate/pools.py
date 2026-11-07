"""Built-in fictional value lists. No external or personal data is used."""
from __future__ import annotations

FIRST_NAMES = (
    "Aarav", "Abena", "Adele", "Aiko", "Alana", "Amir", "Ana", "Andre", "Asha", "Ben",
    "Bianca", "Caleb", "Carla", "Chen", "Clara", "Daniel", "Dara", "Deepa", "Diego", "Elena",
    "Emeka", "Erin", "Farah", "Felix", "Gita", "Grace", "Hana", "Hugo", "Imani", "Ines",
    "Ivan", "Jada", "Jonas", "Kai", "Kavya", "Kofi", "Lara", "Leo", "Lina", "Luis",
    "Maya", "Mei", "Mira", "Nadia", "Nikhil", "Noah", "Omar", "Priya", "Quinn", "Rafael",
    "Rina", "Sam", "Sana", "Tara", "Theo", "Uma", "Vera", "Wei", "Yara", "Zane",
)

LAST_NAMES = (
    "Abara", "Acosta", "Adler", "Ahmed", "Alvarez", "Arora", "Bailey", "Banerjee", "Barnes", "Bello",
    "Berg", "Bose", "Brooks", "Campos", "Carter", "Chandra", "Chavez", "Cole", "Costa", "Das",
    "Dawson", "Delgado", "Diaz", "Dixon", "Duarte", "Ellis", "Eze", "Fernandez", "Fischer", "Flores",
    "Foster", "Gomez", "Gupta", "Hale", "Hansen", "Hart", "Hayes", "Ibrahim", "Iyer", "Jensen",
    "Joshi", "Kapoor", "Kato", "Keller", "Khan", "Kim", "Lam", "Larsen", "Lopez", "Mehta",
    "Mendes", "Miller", "Mori", "Nair", "Nguyen", "Novak", "Okafor", "Olsen", "Ortiz", "Osei",
    "Park", "Patel", "Perez", "Quinn", "Rao", "Reddy", "Reyes", "Rossi", "Saito", "Santos",
    "Sharma", "Silva", "Singh", "Tan", "Torres", "Varga", "Verma", "Walsh", "Wong", "Young",
)

STREET_NAMES = (
    "Alder", "Amber", "Ash", "Aspen", "Beacon", "Birch", "Bramble", "Briar", "Brook", "Cedar",
    "Chestnut", "Clover", "Cobble", "Copper", "Coral", "Crescent", "Cypress", "Dale", "Elm", "Ember",
    "Fairview", "Fern", "Field", "Finch", "Fox", "Garden", "Glen", "Granite", "Harbor", "Hazel",
    "Heather", "Hickory", "Hill", "Holly", "Ivy", "Juniper", "Lake", "Laurel", "Linden", "Maple",
    "Meadow", "Mill", "Moss", "Oak", "Orchard", "Otter", "Park", "Pine", "Quarry", "Raven",
    "Ridge", "River", "Rowan", "Sage", "Spruce", "Stone", "Summit", "Willow", "Wren", "Yarrow",
)

# Canonical suffix -> abbreviated form. Both appear in data so that matching needs normalising.
STREET_SUFFIXES = {
    "Street": "St",
    "Avenue": "Ave",
    "Road": "Rd",
    "Lane": "Ln",
    "Drive": "Dr",
    "Court": "Ct",
}

CITIES = (
    "Alderbrook", "Ashcombe", "Bellhaven", "Briarford", "Brookmere", "Cedarwick", "Clearhollow",
    "Coppergate", "Dunmeadow", "Eastmarch", "Elmhurst Vale", "Fernhaven", "Glenmoor", "Greywater",
    "Harrowfield", "Hollowbrook", "Kestrel Bay", "Larkspur Falls", "Maplecross", "Northfen",
    "Oakmere", "Pinecrest Hollow", "Ravensholt", "Silverbrook", "Westmarch",
)

EMAIL_DOMAINS = ("example.com", "example.org", "example.net")

PROVIDER_NAME_WORDS = (
    "Apex", "Beacon", "Bluebird", "Cornerstone", "Evergreen", "First Choice", "Harbor", "Horizon",
    "Keystone", "Landmark", "Liberty", "Meridian", "Northstar", "Pioneer", "Precision", "Reliable",
    "Riverside", "Summit", "Trusted", "Unity",
)

PROVIDER_NAME_SUFFIXES = {
    "REPAIRER": ("Auto Repair", "Collision Center", "Home Restoration", "Body Works"),
    "MEDICAL": ("Medical Clinic", "Family Practice", "Physiotherapy", "Imaging Center"),
    "SERVICE": ("Towing", "Legal Services", "Claims Support", "Recovery Services"),
}

# Slots: {place} is a location word, {time} a time of day, {detail} an incident-specific detail.
NARRATIVE_TEMPLATES = {
    "COLLISION": (
        "Another vehicle struck my car at the {place} in the {time}; {detail}.",
        "I was hit from behind while stopped near the {place} during the {time}; {detail}.",
        "Collision while turning at the {place} in the {time}, {detail}.",
        "A driver failed to yield at the {place} this {time} and {detail}.",
    ),
    "THEFT": (
        "Items were stolen from my property near the {place} during the {time}; {detail}.",
        "I returned in the {time} to find a break-in near the {place}, {detail}.",
        "Theft reported after the {time} close to the {place}; {detail}.",
    ),
    "INJURY": (
        "I was injured near the {place} in the {time}; {detail}.",
        "Injury after a fall at the {place} during the {time}, {detail}.",
        "I needed treatment after an accident by the {place} this {time}; {detail}.",
    ),
    "WATER_DAMAGE": (
        "A pipe burst in the {time} and water spread from the {place}; {detail}.",
        "Water leaked overnight around the {place}, found in the {time}; {detail}.",
        "Flooding near the {place} in the {time} damaged the home, {detail}.",
    ),
    "FIRE": (
        "A small fire started by the {place} in the {time}; {detail}.",
        "Fire damage near the {place} during the {time}, {detail}.",
        "Smoke and fire affected the area by the {place} this {time}; {detail}.",
    ),
    "ILLNESS": (
        "I developed symptoms in the {time} and visited a clinic near the {place}; {detail}.",
        "Treatment was needed for an illness that began in the {time}, {detail}.",
        "Sudden illness in the {time} near the {place}; {detail}.",
    ),
}

NARRATIVE_PLACES = {
    "COLLISION": ("junction", "roundabout", "parking lot", "traffic light", "highway ramp", "school crossing"),
    "THEFT": ("garage", "driveway", "back door", "shopping center", "side gate", "parking lot"),
    "INJURY": ("sidewalk", "stairway", "parking lot", "bus stop", "office entrance", "market"),
    "WATER_DAMAGE": ("kitchen", "bathroom", "basement", "laundry room", "upstairs hallway"),
    "FIRE": ("kitchen", "garage", "storage room", "fuse box", "back porch"),
    "ILLNESS": ("city center", "bus station", "workplace", "community hall", "pharmacy"),
}

NARRATIVE_TIMES = ("early morning", "morning", "afternoon", "evening", "late evening")

NARRATIVE_DETAILS = {
    "COLLISION": ("the front bumper was damaged", "the rear door was dented", "the side mirror broke",
                  "the headlight was smashed", "the wheel arch was bent", "the car could not be driven"),
    "THEFT": ("a laptop was taken", "tools were missing", "a bicycle was taken", "the lock was forced",
              "a window was broken", "the police were informed"),
    "INJURY": ("my wrist was sprained", "my knee was bruised", "my back was strained",
               "I needed stitches", "my ankle was swollen", "an X-ray was advised"),
    "WATER_DAMAGE": ("the floor was soaked", "the ceiling was stained", "the carpet was ruined",
                     "the cabinets warped", "a plumber was called"),
    "FIRE": ("the wall was scorched", "the wiring was damaged", "the fire service attended",
             "appliances were ruined", "smoke damaged the ceiling"),
    "ILLNESS": ("a fever continued for days", "tests were ordered", "medication was prescribed",
                "a specialist was recommended", "rest was advised"),
}

SERVICE_CODES = {
    "REPAIR": ("PARTS", "LABOR", "PAINT", "INSPECTION", "MATERIALS"),
    "MEDICAL": ("CONSULT", "IMAGING", "THERAPY", "MEDICATION", "LAB_TEST"),
    "TOWING": ("TOW", "STORAGE", "RECOVERY"),
    "LEGAL": ("LEGAL_REVIEW", "FILING", "REPORT"),
}
