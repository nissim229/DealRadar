"""
location_data.py
Curated state -> major-city name lists backing the hunt-criteria location
picker (components/strategy_config.py). Deliberately holds only city NAMES,
not coordinates - coordinates are resolved on demand via the app's existing
geocoder (agent_engine.validate_and_geocode_location, geopy/Nominatim) and
cached in database.py's city_coords_cache table, so a wrong hand-typed
coordinate here can never reproduce the "wrong city" bug this picker exists
to fix. This is a curated list of major cities per state, not an exhaustive
one - a smaller town not listed here is still reachable via the ZIP code
field or (for existing/legacy searches) the old free-text location field.
"""

US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan",
    "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
]

US_CITIES_BY_STATE = {
    "Alabama": ["Birmingham", "Montgomery", "Huntsville", "Mobile", "Tuscaloosa", "Hoover", "Dothan", "Auburn", "Decatur", "Madison"],
    "Alaska": ["Anchorage", "Fairbanks", "Juneau", "Wasilla", "Sitka", "Kenai", "Kodiak"],
    "Arizona": ["Phoenix", "Tucson", "Mesa", "Chandler", "Scottsdale", "Glendale", "Gilbert", "Tempe", "Peoria", "Surprise", "Flagstaff", "Yuma"],
    "Arkansas": ["Little Rock", "Fayetteville", "Fort Smith", "Springdale", "Jonesboro", "Rogers", "Conway", "Bentonville"],
    "California": ["Los Angeles", "San Diego", "San Jose", "San Francisco", "Fresno", "Sacramento", "Long Beach", "Oakland", "Bakersfield", "Anaheim", "Santa Ana", "Riverside", "Irvine", "San Bernardino", "Chula Vista", "Fremont", "Stockton", "Modesto", "Palo Alto", "Berkeley"],
    "Colorado": ["Denver", "Colorado Springs", "Aurora", "Fort Collins", "Lakewood", "Thornton", "Arvada", "Westminster", "Pueblo", "Boulder", "Greeley", "Longmont", "Loveland", "Golden", "Broomfield"],
    "Connecticut": ["Bridgeport", "New Haven", "Stamford", "Hartford", "Waterbury", "Norwalk", "Danbury", "New Britain", "Greenwich"],
    "Delaware": ["Wilmington", "Dover", "Newark", "Middletown", "Bear", "Smyrna"],
    "District of Columbia": ["Washington"],
    "Florida": ["Jacksonville", "Miami", "Tampa", "Orlando", "St. Petersburg", "Hialeah", "Tallahassee", "Port St. Lucie", "Cape Coral", "Fort Lauderdale", "Pembroke Pines", "Gainesville", "Naples", "Sarasota", "Boca Raton", "West Palm Beach"],
    "Georgia": ["Atlanta", "Augusta", "Columbus", "Macon", "Savannah", "Athens", "Sandy Springs", "Roswell", "Alpharetta", "Marietta"],
    "Hawaii": ["Honolulu", "Hilo", "Kailua", "Kapolei", "Kaneohe", "Waipahu"],
    "Idaho": ["Boise", "Meridian", "Nampa", "Idaho Falls", "Pocatello", "Coeur d'Alene", "Twin Falls"],
    "Illinois": ["Chicago", "Aurora", "Naperville", "Joliet", "Rockford", "Springfield", "Elgin", "Peoria", "Champaign", "Evanston", "Schaumburg"],
    "Indiana": ["Indianapolis", "Fort Wayne", "Evansville", "South Bend", "Carmel", "Fishers", "Bloomington", "Lafayette"],
    "Iowa": ["Des Moines", "Cedar Rapids", "Davenport", "Sioux City", "Iowa City", "Ames", "West Des Moines"],
    "Kansas": ["Wichita", "Overland Park", "Kansas City", "Topeka", "Olathe", "Lawrence", "Manhattan"],
    "Kentucky": ["Louisville", "Lexington", "Bowling Green", "Owensboro", "Covington", "Frankfort"],
    "Louisiana": ["New Orleans", "Baton Rouge", "Shreveport", "Lafayette", "Lake Charles", "Kenner", "Bossier City"],
    "Maine": ["Portland", "Lewiston", "Bangor", "South Portland", "Auburn", "Augusta"],
    "Maryland": ["Baltimore", "Columbia", "Germantown", "Silver Spring", "Frederick", "Rockville", "Annapolis", "Bethesda", "Gaithersburg"],
    "Massachusetts": ["Boston", "Worcester", "Springfield", "Cambridge", "Lowell", "Brockton", "Quincy", "Newton", "Somerville"],
    "Michigan": ["Detroit", "Grand Rapids", "Warren", "Sterling Heights", "Ann Arbor", "Lansing", "Flint", "Dearborn", "Livonia", "Troy"],
    "Minnesota": ["Minneapolis", "St. Paul", "Rochester", "Duluth", "Bloomington", "Brooklyn Park", "Plymouth", "Eden Prairie"],
    "Mississippi": ["Jackson", "Gulfport", "Southaven", "Hattiesburg", "Biloxi", "Meridian"],
    "Missouri": ["Kansas City", "St. Louis", "Springfield", "Columbia", "Independence", "Lee's Summit", "St. Joseph", "Chesterfield"],
    "Montana": ["Billings", "Missoula", "Great Falls", "Bozeman", "Butte", "Helena"],
    "Nebraska": ["Omaha", "Lincoln", "Bellevue", "Grand Island", "Kearney"],
    "Nevada": ["Las Vegas", "Henderson", "Reno", "North Las Vegas", "Sparks", "Carson City"],
    "New Hampshire": ["Manchester", "Nashua", "Concord", "Derry", "Dover", "Portsmouth"],
    "New Jersey": ["Newark", "Jersey City", "Paterson", "Elizabeth", "Trenton", "Edison", "Woodbridge", "Hoboken", "Princeton"],
    "New Mexico": ["Albuquerque", "Las Cruces", "Rio Rancho", "Santa Fe", "Roswell"],
    "New York": ["New York City", "Buffalo", "Rochester", "Yonkers", "Syracuse", "Albany", "New Rochelle", "Mount Vernon", "White Plains", "Ithaca"],
    "North Carolina": ["Charlotte", "Raleigh", "Greensboro", "Durham", "Winston-Salem", "Fayetteville", "Cary", "Wilmington", "Asheville", "Chapel Hill"],
    "North Dakota": ["Fargo", "Bismarck", "Grand Forks", "Minot", "West Fargo"],
    "Ohio": ["Columbus", "Cleveland", "Cincinnati", "Toledo", "Akron", "Dayton", "Parma", "Canton", "Youngstown"],
    "Oklahoma": ["Oklahoma City", "Tulsa", "Norman", "Broken Arrow", "Edmond", "Lawton"],
    "Oregon": ["Portland", "Salem", "Eugene", "Gresham", "Hillsboro", "Bend", "Beaverton", "Medford"],
    "Pennsylvania": ["Philadelphia", "Pittsburgh", "Allentown", "Erie", "Reading", "Scranton", "Bethlehem", "Lancaster", "Harrisburg", "State College"],
    "Rhode Island": ["Providence", "Warwick", "Cranston", "Pawtucket", "East Providence", "Newport"],
    "South Carolina": ["Columbia", "Charleston", "North Charleston", "Mount Pleasant", "Rock Hill", "Greenville", "Myrtle Beach"],
    "South Dakota": ["Sioux Falls", "Rapid City", "Aberdeen", "Brookings"],
    "Tennessee": ["Nashville", "Memphis", "Knoxville", "Chattanooga", "Clarksville", "Murfreesboro", "Franklin"],
    "Texas": ["Houston", "San Antonio", "Dallas", "Austin", "Fort Worth", "El Paso", "Arlington", "Corpus Christi", "Plano", "Irving", "Frisco", "McKinney", "Denton", "Round Rock", "The Woodlands"],
    "Utah": ["Salt Lake City", "West Valley City", "Provo", "West Jordan", "Orem", "Sandy", "Ogden", "Park City"],
    "Vermont": ["Burlington", "South Burlington", "Rutland", "Montpelier"],
    "Virginia": ["Virginia Beach", "Norfolk", "Chesapeake", "Richmond", "Newport News", "Alexandria", "Hampton", "Arlington", "Roanoke", "Charlottesville"],
    "Washington": ["Seattle", "Spokane", "Tacoma", "Vancouver", "Bellevue", "Kent", "Everett", "Redmond", "Bellingham", "Olympia"],
    "West Virginia": ["Charleston", "Huntington", "Morgantown", "Parkersburg", "Wheeling"],
    "Wisconsin": ["Milwaukee", "Madison", "Green Bay", "Kenosha", "Racine", "Appleton", "Eau Claire"],
    "Wyoming": ["Cheyenne", "Casper", "Laramie", "Gillette", "Jackson"],
}
