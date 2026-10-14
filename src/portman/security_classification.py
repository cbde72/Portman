"""Shared classification choices for security metadata and the desktop editor."""
ASSET_TYPES = ('Aktie', 'ETF', 'Fonds', 'Anleihe', 'ETC', 'Option', 'Krypto', 'Rohstoff', 'Immobilie', 'Zertifikat', 'Sonstiges')
REGIONS = ('USA', 'Europa', 'Deutschland', 'Welt', 'Japan', 'Emerging Markets',
           'Asien/Pazifik', 'Nordamerika', 'Lateinamerika', 'Afrika', 'Sonstige', 'Unbekannt')
CAP_SIZES = ('Small', 'Mid', 'Large', 'All Cap','Immobilie', 'Nicht zutreffend', 'Unbekannt')
CLASSIFICATION_CHOICES = {'asset_type': ASSET_TYPES, 'region': REGIONS, 'cap_size': CAP_SIZES}
