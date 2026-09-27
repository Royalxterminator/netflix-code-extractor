"""Netflix email extractors, IMAP fetching, and concurrent fetch processing.
Loaded by email_bot.main into one shared runtime context."""

import re
from email_bot.utils import clean_url

# =============================
# FLAG DICTIONARY WITH NAMES
# =============================
FLAG_EMOJIS = {
    'AD': ('🇦🇩', '5474202042299856056', 'Andorra'),
    'AE': ('🇦🇪', '5445069334965657809', 'United Arab Emirates'),
    'AF': ('🇦🇫', '5323300080046847499', 'Afghanistan'),
    'AG': ('🇦🇬', '5201749731021175045', 'Antigua and Barbuda'),
    'AI': ('🇦🇮', '5453882247079805914', 'Anguilla'),
    'AL': ('🇦🇱', '5474150171979822886', 'Albania'),
    'AM': ('🇦🇲', '5411397985365927767', 'Armenia'),
    'AO': ('🇦🇴', '5222327945833490823', 'Angola'),
    'AQ': ('🇦🇶', '5222324569989195203', 'Antarctica'),
    'AR': ('🇦🇷', '5242367945409044100', 'Argentina'),
    'AS': ('🇦🇸', '5202063633000971848', 'American Samoa'),
    'AT': ('🇦🇹', '5411354653440877283', 'Austria'),
    'AU': ('🇦🇺', '5348289501150064920', 'Australia'),
    'AW': ('🇦🇼', '5219728300913473484', 'Aruba'),
    'AX': ('🇦🇽', '5467371334902234904', 'Åland Islands'),
    'AZ': ('🇦🇿', '5224542095963859210', 'Azerbaijan'),
    'BA': ('🇧🇦', '5402403409020071544', 'Bosnia and Herzegovina'),
    'BB': ('🇧🇧', '5224342921150474196', 'Barbados'),
    'BD': ('🇧🇩', '5222066820411829362', 'Bangladesh'),
    'BE': ('🇧🇪', '5411322170603220759', 'Belgium'),
    'BF': ('🇧🇫', '5188547100337514183', 'Burkina Faso'),
    'BG': ('🇧🇬', '5409301577469012036', 'Bulgaria'),
    'BH': ('🇧🇭', '5229000435225868073', 'Bahrain'),
    'BI': ('🇧🇮', '5362040796725919893', 'Burundi'),
    'BJ': ('🇧🇯', '5449793189105904669', 'Benin'),
    'BL': ('🇧🇱', '5201980512498892355', 'Saint Barthélemy'),
    'BM': ('🇧🇲', '5454310889110911313', 'Bermuda'),
    'BN': ('🇧🇳', '5467379916246891834', 'Brunei'),
    'BO': ('🇧🇴', '5361795124596586531', 'Bolivia'),
    'BQ': ('🇧🇶', '5201899509415690273', 'Bonaire, Sint Eustatius and Saba'),
    'BR': ('🇧🇷', '5474188762260971755', 'Brazil'),
    'BS': ('🇧🇸', '5447263947289798143', 'Bahamas'),
    'BT': ('🇧🇹', '5406837288443329315', 'Bhutan'),
    'BW': ('🇧🇼', '5406819387019640027', 'Botswana'),
    'BY': ('🇧🇾', '5370547112599629768', 'Belarus'),
    'BZ': ('🇧🇿', '5219753873148756545', 'Belize'),
    'CA': ('🇨🇦', '5348476800378874158', 'Canada'),
    'CC': ('🇨🇨', '5467919097851296949', 'Cocos Islands'),
    'CD': ('🇨🇩', '5271956198449492231', 'DR Congo'),
    'CF': ('🇨🇫', '5406828810177887232', 'Central African Republic'),
    'CG': ('🇨🇬', '5406715770933625431', 'Congo'),
    'CH': ('🇨🇭', '5471897070791047022', 'Switzerland'),
    'CI': ('🇨🇮', '5411136859944265277', 'Côte d\'Ivoire'),
    'CK': ('🇨🇰', '5454288873108553536', 'Cook Islands'),
    'CL': ('🇨🇱', '5222267026017365103', 'Chile'),
    'CM': ('🇨🇲', '5474215287978994431', 'Cameroon'),
    'CN': ('🇨🇳', '5447548939844725331', 'China'),
    'CO': ('🇨🇴', '5323705520664625325', 'Colombia'),
    'CR': ('🇨🇷', '5269317821514399900', 'Costa Rica'),
    'CU': ('🇨🇺', '5361655525274567119', 'Cuba'),
    'CV': ('🇨🇻', '5201701545783084873', 'Cape Verde'),
    'CW': ('🇨🇼', '5201679761708956718', 'Curaçao'),
    'CX': ('🇨🇽', '5467923633336760956', 'Christmas Island'),
    'CY': ('🇨🇾', '5228993593342967183', 'Cyprus'),
    'CZ': ('🇨🇿', '5449806048237988326', 'Czechia'),
    'DE': ('🇩🇪', '5409324508299405361', 'Germany'),
    'DJ': ('🇩🇯', '5460861775094228949', 'Djibouti'),
    'DK': ('🇩🇰', '5402338567898804415', 'Denmark'),
    'DM': ('🇩🇲', '5199916548784930671', 'Dominica'),
    'DO': ('🇩🇴', '5361899926093577217', 'Dominican Republic'),
    'DZ': ('🇩🇿', '5269237836338444690', 'Algeria'),
    'EC': ('🇪🇨', '5361898697732930827', 'Ecuador'),
    'EE': ('🇪🇪', '5409310974857455487', 'Estonia'),
    'EG': ('🇪🇬', '5226715650063351089', 'Egypt'),
    'EH': ('🇪🇭', '5447581882243884899', 'Western Sahara'),
    'ER': ('🇪🇷', '5407075023473099528', 'Eritrea'),
    'ES': ('🇪🇸', '5474302664793660441', 'Spain'),
    'ET': ('🇪🇹', '5269306474210802594', 'Ethiopia'),
    'EU': ('🇪🇺', '5229068501867574283', 'European Union'),
    'FI': ('🇫🇮', '5404854954877794218', 'Finland'),
    'FJ': ('🇫🇯', '5454170138737656776', 'Fiji'),
    'FK': ('🇫🇰', '5454238329933414079', 'Falkland Islands'),
    'FM': ('🇫🇲', '5220030722445689828', 'Micronesia'),
    'FO': ('🇫🇴', '5474658584438518793', 'Faroe Islands'),
    'FR': ('🇫🇷', '5467600364033286654', 'France'),
    'GA': ('🇬🇦', '5409135181846030501', 'Gabon'),
    'GB': ('🇬🇧', '5458416160586342331', 'United Kingdom'),
    'GD': ('🇬🇩', '5467679155208338491', 'Grenada'),
    'GE': ('🇬🇪', '5474255312779227745', 'Georgia'),
    'GF': ('🇬🇫', '5201874658734913043', 'French Guiana'),
    'GG': ('🇬🇬', '5474240112889966563', 'Guernsey'),
    'GH': ('🇬🇭', '5474279983071373042', 'Ghana'),
    'GI': ('🇬🇮', '5474323418075640555', 'Gibraltar'),
    'GL': ('🇬🇱', '5222124020786276833', 'Greenland'),
    'GM': ('🇬🇲', '5406748640318341750', 'Gambia'),
    'GN': ('🇬🇳', '5409278805552408574', 'Guinea'),
    'GP': ('🇬🇵', '5467577441792833761', 'Guadeloupe'),
    'GQ': ('🇬🇶', '5447325498466118034', 'Equatorial Guinea'),
    'GR': ('🇬🇷', '5368324428369245416', 'Greece'),
    'GS': ('🇬🇸', '5453888410357874002', 'South Georgia'),
    'GT': ('🇬🇹', '5364200950527440343', 'Guatemala'),
    'GU': ('🇬🇺', '5219746992611149056', 'Guam'),
    'GW': ('🇬🇼', '5449530105179153986', 'Guinea-Bissau'),
    'GY': ('🇬🇾', '5407102214911049522', 'Guyana'),
    'HK': ('🇭🇰', '5222110861006480536', 'Hong Kong'),
    'HN': ('🇭🇳', '5224469807369298850', 'Honduras'),
    'HR': ('🇭🇷', '5244534472942036867', 'Croatia'),
    'HT': ('🇭🇹', '5364137621234661316', 'Haiti'),
    'HU': ('🇭🇺', '5411094472912021895', 'Hungary'),
    'IC': ('🇮🇨', '5201891065509988737', 'Canary Islands'),
    'ID': ('🇮🇩', '5291997937486800451', 'Indonesia'),
    'IE': ('🇮🇪', '5409154848501280108', 'Ireland'),
    'IL': ('🇮🇱', '5334541821936676295', 'Israel'),
    'IM': ('🇮🇲', '5472299891478770319', 'Isle of Man'),
    'IN': ('🇮🇳', '5445209411029050250', 'India'),
    'IO': ('🇮🇴', '5454372435992263772', 'British Indian Ocean Territory'),
    'IQ': ('🇮🇶', '5228816473186646845', 'Iraq'),
    'IR': ('🇮🇷', '5269324659102335906', 'Iran'),
    'IS': ('🇮🇸', '5471976282872886845', 'Iceland'),
    'IT': ('🇮🇹', '5445318790961176303', 'Italy'),
    'JE': ('🇯🇪', '5474598673939706027', 'Jersey'),
    'JM': ('🇯🇲', '5406971115329306458', 'Jamaica'),
    'JO': ('🇯🇴', '5460833277986220948', 'Jordan'),
    'JP': ('🇯🇵', '5460965305280899224', 'Japan'),
    'KE': ('🇰🇪', '5269450213881298384', 'Kenya'),
    'KG': ('🇰🇬', '5361789206131654939', 'Kyrgyzstan'),
    'KH': ('🇰🇭', '5361821882242843520', 'Cambodia'),
    'KI': ('🇰🇮', '5219861874396380489', 'Kiribati'),
    'KM': ('🇰🇲', '5406584486668287374', 'Comoros'),
    'KN': ('🇰🇳', '5201987526180487365', 'Saint Kitts and Nevis'),
    'KP': ('🇰🇵', '5323614097990759797', 'North Korea'),
    'KR': ('🇰🇷', '5460922127974672624', 'South Korea'),
    'KW': ('🇰🇼', '5449773801623529818', 'Kuwait'),
    'KY': ('🇰🇾', '5453990278392198637', 'Cayman Islands'),
    'KZ': ('🇰🇿', '5228885231318088701', 'Kazakhstan'),
    'LA': ('🇱🇦', '5361951113513811639', 'Laos'),
    'LB': ('🇱🇧', '5361692745461153142', 'Lebanon'),
    'LC': ('🇱🇨', '5222011638672010440', 'Saint Lucia'),
    'LI': ('🇱🇮', '5471958488823379994', 'Liechtenstein'),
    'LK': ('🇱🇰', '5321041498479803449', 'Sri Lanka'),
    'LR': ('🇱🇷', '5407118935218732319', 'Liberia'),
    'LS': ('🇱🇸', '5406594188999409765', 'Lesotho'),
    'LT': ('🇱🇹', '5408945739428537525', 'Lithuania'),
    'LU': ('🇱🇺', '5411220985468692097', 'Luxembourg'),
    'LV': ('🇱🇻', '5271622977706802760', 'Latvia'),
    'LY': ('🇱🇾', '5222179640612759469', 'Libya'),
    'MA': ('🇲🇦', '5242363633261879468', 'Morocco'),
    'MC': ('🇲🇨', '5411494252762900094', 'Monaco'),
    'MD': ('🇲🇩', '5474405911512494548', 'Moldova'),
    'ME': ('🇲🇪', '5474360316139678982', 'Montenegro'),
    'MG': ('🇲🇬', '5449881540878149184', 'Madagascar'),
    'MH': ('🇲🇭', '5467786245922897695', 'Marshall Islands'),
    'MK': ('🇲🇰', '5474167137100642230', 'North Macedonia'),
    'ML': ('🇲🇱', '5408879966299366345', 'Mali'),
    'MM': ('🇲🇲', '5188450381968975674', 'Myanmar'),
    'MN': ('🇲🇳', '5407123139991711704', 'Mongolia'),
    'MO': ('🇲🇴', '5407087161050677184', 'Macau'),
    'MP': ('🇲🇵', '5202210997623865737', 'Northern Mariana Islands'),
    'MQ': ('🇲🇶', '5467708193482230367', 'Martinique'),
    'MR': ('🇲🇷', '5404566049607663230', 'Mauritania'),
    'MS': ('🇲🇸', '5454264997385354230', 'Montserrat'),
    'MT': ('🇲🇹', '5474306826616977069', 'Malta'),
    'MU': ('🇲🇺', '5269598669425883845', 'Mauritius'),
    'MV': ('🇲🇻', '5220181858049867767', 'Maldives'),
    'MW': ('🇲🇼', '5323397270861789770', 'Malawi'),
    'MX': ('🇲🇽', '5348366041762247484', 'Mexico'),
    'MY': ('🇲🇾', '5321511982082311992', 'Malaysia'),
    'MZ': ('🇲🇿', '5449858266450372318', 'Mozambique'),
    'NA': ('🇳🇦', '5406829106530631979', 'Namibia'),
    'NC': ('🇳🇨', '5217877260203214750', 'New Caledonia'),
    'NE': ('🇳🇪', '5323807148180781123', 'Niger'),
    'NF': ('🇳🇫', '5220023820433246013', 'Norfolk Island'),
    'NG': ('🇳🇬', '5411389721848850059', 'Nigeria'),
    'NI': ('🇳🇮', '5361920765274896077', 'Nicaragua'),
    'NL': ('🇳🇱', '5411462040508179549', 'Netherlands'),
    'NO': ('🇳🇴', '5402403426199941953', 'Norway'),
    'NP': ('🇳🇵', '5431757436019034791', 'Nepal'),
    'NR': ('🇳🇷', '5219736018969706104', 'Nauru'),
    'NU': ('🇳🇺', '5454166191662710990', 'Niue'),
    'NZ': ('🇳🇿', '5269656166153075133', 'New Zealand'),
    'OM': ('🇴🇲', '5271930158062779008', 'Oman'),
    'PA': ('🇵🇦', '5269326815175916732', 'Panama'),
    'PE': ('🇵🇪', '5411241584131845041', 'Peru'),
    'PF': ('🇵🇫', '5469891312473881746', 'French Polynesia'),
    'PG': ('🇵🇬', '5362067494242631646', 'Papua New Guinea'),
    'PH': ('🇵🇭', '5460822682301901437', 'Philippines'),
    'PK': ('🇵🇰', '5271660124878943849', 'Pakistan'),
    'PL': ('🇵🇱', '5411521663244184810', 'Poland'),
    'PM': ('🇵🇲', '5219684114289932668', 'Saint Pierre and Miquelon'),
    'PN': ('🇵🇳', '5454358640557309114', 'Pitcairn Islands'),
    'PR': ('🇵🇷', '5271890283586401784', 'Puerto Rico'),
    'PS': ('🇵🇸', '5449416980035546269', 'Palestine'),
    'PT': ('🇵🇹', '5368543871133300316', 'Portugal'),
    'PW': ('🇵🇼', '5222032872990320500', 'Palau'),
    'PY': ('🇵🇾', '5361895347658440326', 'Paraguay'),
    'QA': ('🇶🇦', '5228889741033748753', 'Qatar'),
    'RE': ('🇷🇪', '5406882407074775001', 'Réunion'),
    'RO': ('🇷🇴', '5409188632714028866', 'Romania'),
    'RS': ('🇷🇸', '5370826057840604180', 'Serbia'),
    'RU': ('🇷🇺', '5398017006165305287', 'Russia'),
    'RW': ('🇷🇼', '5363904460345062292', 'Rwanda'),
    'SA': ('🇸🇦', '5188644677699510586', 'Saudi Arabia'),
    'SB': ('🇸🇧', '5219731088347253660', 'Solomon Islands'),
    'SC': ('🇸🇨', '5219713182628591971', 'Seychelles'),
    'SD': ('🇸🇩', '5449620557190407968', 'Sudan'),
    'SE': ('🇸🇪', '5370994137090767066', 'Sweden'),
    'SG': ('🇸🇬', '5411082949514765841', 'Singapore'),
    'SH': ('🇸🇭', '5453865677095974959', 'Saint Helena'),
    'SI': ('🇸🇮', '5474184123696297291', 'Slovenia'),
    'SK': ('🇸🇰', '5402103981080063896', 'Slovakia'),
    'SL': ('🇸🇱', '5408899933602330691', 'Sierra Leone'),
    'SM': ('🇸🇲', '5228989830951614810', 'San Marino'),
    'SN': ('🇸🇳', '5188523937578887448', 'Senegal'),
    'SO': ('🇸🇴', '5474267330097719943', 'Somalia'),
    'SR': ('🇸🇷', '5467764006582238020', 'Suriname'),
    'SS': ('🇸🇸', '5462910538918929704', 'South Sudan'),
    'ST': ('🇸🇹', '5447304654989829617', 'São Tomé and Príncipe'),
    'SV': ('🇸🇻', '5361657818787102540', 'El Salvador'),
    'SX': ('🇸🇽', '5463204525135373754', 'Sint Maarten'),
    'SY': ('🇸🇾', '5291969728141625850', 'Syria'),
    'SZ': ('🇸🇿', '5406934084121277661', 'Eswatini'),
    'TC': ('🇹🇨', '5452114726303580275', 'Turks and Caicos Islands'),
    'TD': ('🇹🇩', '5409216446922240024', 'Chad'),
    'TF': ('🇹🇫', '5220123287580848769', 'French Southern Territories'),
    'TG': ('🇹🇬', '5361836536671255503', 'Togo'),
    'TH': ('🇹🇭', '5323729877424158571', 'Thailand'),
    'TJ': ('🇹🇯', '5361701021863131570', 'Tajikistan'),
    'TK': ('🇹🇰', '5202199164988963475', 'Tokelau'),
    'TL': ('🇹🇱', '5406823162295893814', 'Timor-Leste'),
    'TM': ('🇹🇲', '5406979563529975578', 'Turkmenistan'),
    'TN': ('🇹🇳', '5364156879868016491', 'Tunisia'),
    'TO': ('🇹🇴', '5467393823350995380', 'Tonga'),
    'TR': ('🇹🇷', '5229155784192965272', 'Turkey'),
    'TT': ('🇹🇹', '5406966803182140950', 'Trinidad and Tobago'),
    'TV': ('🇹🇻', '5453950773283013307', 'Tuvalu'),
    'TW': ('🇹🇼', '5222085043958065224', 'Taiwan'),
    'TZ': ('🇹🇿', '5271990906080212467', 'Tanzania'),
    'UA': ('🇺🇦', '5445118241758257251', 'Ukraine'),
    'UG': ('🇺🇬', '5269533759585139377', 'Uganda'),
    'UN': ('🇺🇳', '5229172577515092717', 'United Nations'),
    'US': ('🇺🇸', '5474446335744680905', 'United States'),
    'UY': ('🇺🇾', '5269511756467682157', 'Uruguay'),
    'UZ': ('🇺🇿', '5445378486711623503', 'Uzbekistan'),
    'VA': ('🇻🇦', '5474599799221137212', 'Vatican City'),
    'VC': ('🇻🇨', '5467544731321908295', 'Saint Vincent and the Grenadines'),
    'VE': ('🇻🇪', '5226864792802705038', 'Venezuela'),
    'VG': ('🇻🇬', '5451631555367681300', 'British Virgin Islands'),
    'VI': ('🇻🇮', '5201888935206207689', 'U.S. Virgin Islands'),
    'VN': ('🇻🇳', '5474626200385104596', 'Vietnam'),
    'VU': ('🇻🇺', '5467876929862384229', 'Vanuatu'),
    'WF': ('🇼🇫', '5219856338183534768', 'Wallis and Futuna'),
    'WS': ('🇼🇸', '5202219231076169414', 'Samoa'),
    'XK': ('🇽🇰', '5474676451502469860', 'Kosovo'),
    'YE': ('🇾🇪', '5409177852346115391', 'Yemen'),
    'YT': ('🇾🇹', '5467650284438175469', 'Mayotte'),
    'ZA': ('🇿🇦', '5323804090164066657', 'South Africa'),
    'ZM': ('🇿🇲', '5323643625890921607', 'Zambia'),
    'ZW': ('🇿🇼', '5362047926371630908', 'Zimbabwe'),
}

# =============================
# EMAIL PROCESSING FUNCTIONS
# =============================
def extract_account_region(text):
    """Extract Country Code from Netflix email SRC footer."""
    # Target formats like: SRC: 61C271AA_863f4b2c_en-GB_IN_EVO
    match = re.search(r'SRC:.*?_([a-zA-Z]{2}-[a-zA-Z]{2})_([A-Z]{2})_', text)
    if match:
        return match.group(2)

    # Fallback if no locale string
    match_evo = re.search(r'_([A-Z]{2})_EVO\b', text)
    if match_evo:
        return match_evo.group(1)

    return None

def extract_login_code(text):
    match = re.search(r'\b(\d{4})\b', text)
    return match.group(1) if match else "No 4-digit code found."
_POST_LOGIN_VERIFICATION_BODIES = (
    "Someone is trying to access your account. If you recognise this request, enter this code to confirm. You'll have 15 minutes before this code expires.",
    "Seseorang mencoba mengakses akunmu. Jika kamu mengenali permintaan ini, masukkan kode ini untuk mengonfirmasi. Kode ini akan kedaluwarsa dalam 15 menit.",
    "มีคนพยายามเข้าใช้บัญชีของคุณ หากจำคำขอนี้ได้ ให้ป้อนรหัสนี้เพื่อยืนยัน รหัสดังกล่าวจะหมดอายุใน 15 นาที",
    "Seseorang cuba mengakses akaun anda. Jika anda mengenali permintaan ini, masukkan kod ini untuk membuat pengesahan. Kod ini akan tamat tempoh dalam masa 15 minit.",
)


def is_verification_code_after_login(subject, body):
    """Return whether an email uses the post-login verification template."""
    text = re.sub(r'\s+', ' ', f"{subject} {body}").strip().lower()
    return any(marker.lower() in text for marker in _POST_LOGIN_VERIFICATION_BODIES)



def extract_verification_code(text):
    """Extract a six-digit code only when the email identifies it as a code.

    Do not return the first six-digit number in the message. Emails commonly
    contain unrelated six-digit values in links, IDs, dates, or examples.
    """
    normalized_text = re.sub(r'\s+', ' ', text or '')
    code_patterns = (
        # English templates.
        r'\b(?:your|the)\s+(?:verification|security|confirmation)\s+code\s*(?:is|:)?\s*(\d{6})\b',
        r'\b(?:verification|security|confirmation)\s+code\s*(?:is|:)?\s*(\d{6})\b',
        r'\b(?:enter|input|type|use)\s+(?:this|the|your)\s+code\s*(?:is|:)?\s*(\d{6})\b',
        r'\b(?:your|the)\s+code\s+(?:is|:)?\s*(\d{6})\b',
        r'\b(\d{6})\s+is\s+your\s+(?:verification|security|confirmation)\s+code\b',
        # Indonesian and Malay templates.
        r'\b(?:kode|kod)\s+(?:verifikasi|pengesahan|keselamatan)\s*(?:anda|kamu)?\s*(?:adalah|ialah|:)?\s*(\d{6})\b',
        r'\b(?:kode|kod)\s*(?:adalah|ialah|:)?\s*(\d{6})\b',
    )

    for pattern in code_patterns:
        match = re.search(pattern, normalized_text, re.IGNORECASE)
        if match:
            return match.group(1)

    # Some localized templates put the code near a verification keyword
    # without using the exact English sentence forms above.
    nearby_patterns = (
        r'(?i)(?:verification|security|confirmation).{0,100}\b(\d{6})\b',
        r'(?i)\b(\d{6})\b.{0,100}(?:verification|security|confirmation)',
    )
    for pattern in nearby_patterns:
        match = re.search(pattern, normalized_text)
        if match:
            return match.group(1)

    # HTML email templates sometimes render one digit per span, producing
    # values like "1 2 3 4 5 6" after HTML stripping.
    if re.search(r'(?:verification|security|confirmation|\bcode\b)', normalized_text, re.IGNORECASE):
        for match in re.finditer(r'(?<!\d)(?:\d[\s-]?){6}(?!\d)', normalized_text):
            candidate = re.sub(r'\D', '', match.group(0))
            if len(candidate) == 6:
                return candidate

    return "No 6-digit verification code found."


def extract_verification_code_after_login(subject, body):
    """Extract the six-digit code from the post-login verification email."""
    if is_verification_code_after_login(subject, body):
        matches = re.findall(r'(?<!\d)(\d{6})(?!\d)', body)
        if matches:
            return matches[0]

    return None

def extract_reset_link(text):
    match = re.search(r'(https://www\.netflix\.com/password\?[^\s>"\'\)\]]+)', text)
    if match:
        return clean_url(match.group(1))
    return "No reset link found."

def extract_household_links(text):
    patterns = [
        r'(https://www\.netflix\.com/account/travel/[^\s>"\'\)\]]+)',
        r'(https://www\.netflix\.com/account/update-primary-location\?[^\s>"\'\)\]]+)',
        r'(https://www\.netflix\.com/account/confirmdevice\?[^\s>"\'\)\]]+)'
    ]
    links = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for url in matches:
            cleaned = clean_url(url)
            if cleaned not in links:
                links.append(cleaned)
    return '\n'.join(links) if links else "No household links found."

def extract_verify_email_link(text):
    match = re.search(r'(https://www\.netflix\.com/verifyemail\?[^\s>"\'\)\]]+)', text)
    if match:
        return clean_url(match.group(1))
    return "No verification link found."

def extract_tv_login_link(text):
    """Extracts the TV Login link pattern"""
    match = re.search(r'(https://www\.netflix\.com/ilum\?code=[^\s>"\'\)\]]+)', text)
    if match:
        return clean_url(match.group(1))
    return "No TV login link found."
