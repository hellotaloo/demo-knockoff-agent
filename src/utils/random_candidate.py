"""
Random candidate generator for simulation mode.

Generates realistic Belgian/Dutch names and profiles for testing
the screening chat without real candidates.
"""

import random
import uuid
from dataclasses import dataclass
from typing import Optional


# Belgian/Dutch first names (mix of common names)
FIRST_NAMES_MALE = [
    "Jan", "Pieter", "Thomas", "Kevin", "Bart", "Wim", "Koen", "Yves",
    "Mohammed", "Mehdi", "Ahmed", "Bram", "Stijn", "Dries", "Jens",
    "Mathias", "Robin", "Sander", "Joris", "Nick", "Tom", "Luc",
    "Marc", "Filip", "Kristof", "Jeroen", "Dieter", "Wouter", "Glenn",
    "Davy", "Steven", "Dennis", "Michael", "David", "Raf", "Geert"
]

FIRST_NAMES_FEMALE = [
    "Emma", "Laura", "Julie", "Sarah", "Charlotte", "Marie", "Lien",
    "Eline", "Lisa", "Noor", "Fatima", "Amira", "Lotte", "An", "Katrien",
    "Els", "Nathalie", "Sofie", "Karen", "Inge", "Joke", "Ellen",
    "Annelies", "Silke", "Jolien", "Tine", "Liesbeth", "Greet", "Ilse",
    "Veerle", "Kim", "Sandra", "Valerie", "Petra", "Marleen", "Leen"
]

# Common Belgian/Dutch last names
LAST_NAMES = [
    "Janssen", "Peeters", "Maes", "Jacobs", "Mertens", "Willems",
    "Claes", "Goossens", "Wouters", "De Smedt", "Hermans", "Peters",
    "Janssens", "Van Damme", "Van den Berg", "De Graef", "Lemmens",
    "Claessens", "Stevens", "Hendrickx", "Van de Velde", "Martens",
    "Cools", "Bogaert", "De Cock", "Aerts", "Lambert", "Vandenberghe",
    "Van den Broeck", "De Backer", "Desmet", "Van Hoeck", "Pauwels",
    "El Amrani", "Benali", "Yilmaz", "Ozturk", "Diallo", "Bakker",
    "De Vries", "Van Dijk", "Smeets", "Leemans", "Raes", "Bernaerts"
]

# Belgian cities/regions for realistic profiles
CITIES = [
    "Antwerpen", "Gent", "Brussel", "Leuven", "Brugge", "Mechelen",
    "Hasselt", "Kortrijk", "Aalst", "Roeselare", "Genk", "Sint-Niklaas",
    "Dendermonde", "Turnhout", "Diest", "Tienen", "Herentals", "Mol",
    "Beringen", "Lommel", "Vilvoorde", "Halle", "Zaventem", "Wetteren"
]

# Phone number prefixes (Belgian mobile)
PHONE_PREFIXES = ["0470", "0471", "0472", "0473", "0474", "0475", "0476", "0477", "0478", "0479",
                  "0480", "0481", "0482", "0483", "0484", "0485", "0486", "0487", "0488", "0489",
                  "0490", "0491", "0492", "0493", "0494", "0495", "0496", "0497", "0498", "0499"]


@dataclass
class RandomCandidate:
    """A randomly generated candidate for simulation."""
    id: str
    first_name: str
    last_name: str
    full_name: str
    email: str
    phone: str
    city: str
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "city": self.city
        }


def generate_random_candidate(gender: Optional[str] = None) -> RandomCandidate:
    """
    Generate a random candidate with realistic Belgian/Dutch profile.
    
    Args:
        gender: Optional 'male' or 'female'. If None, randomly chosen.
    
    Returns:
        RandomCandidate with generated profile data
    """
    # Choose gender if not specified
    if gender is None:
        gender = random.choice(["male", "female"])
    
    # Pick names
    if gender == "male":
        first_name = random.choice(FIRST_NAMES_MALE)
    else:
        first_name = random.choice(FIRST_NAMES_FEMALE)
    
    last_name = random.choice(LAST_NAMES)
    full_name = f"{first_name} {last_name}"
    
    # Generate email (lowercase, handle spaces in last names)
    email_last = last_name.lower().replace(" ", "").replace("'", "")
    email_first = first_name.lower()
    # Add random number to avoid duplicates
    email_num = random.randint(1, 999)
    email = f"{email_first}.{email_last}{email_num}@example.com"
    
    # Generate phone
    phone_prefix = random.choice(PHONE_PREFIXES)
    phone_suffix = "".join([str(random.randint(0, 9)) for _ in range(6)])
    phone = f"+32{phone_prefix[1:]}{phone_suffix}"
    
    # Pick city
    city = random.choice(CITIES)
    
    return RandomCandidate(
        id=str(uuid.uuid4()),
        first_name=first_name,
        last_name=last_name,
        full_name=full_name,
        email=email,
        phone=phone,
        city=city
    )


def generate_batch(count: int = 10) -> list[RandomCandidate]:
    """Generate a batch of random candidates."""
    return [generate_random_candidate() for _ in range(count)]


# Quick test
if __name__ == "__main__":
    for _ in range(5):
        candidate = generate_random_candidate()
        print(f"{candidate.full_name} ({candidate.email}) - {candidate.city}")
