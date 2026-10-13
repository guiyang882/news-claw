"""Pure parser for the SEC's public company-submissions API; no network access."""
from datetime import date, datetime, timezone
import re


def parse_submissions(payload, cik, forms):
    if not isinstance(payload, dict) or str(payload.get('cik', '')).zfill(10) != str(cik).zfill(10):
        raise ValueError('SEC response belongs to another company')
    name = payload.get('name')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('SEC response has no company name')
    recent = payload['filings']['recent']
    keys = ('accessionNumber', 'filingDate', 'reportDate', 'acceptanceDateTime', 'form', 'primaryDocument')
    if any(not isinstance(recent.get(key), list) for key in keys):
        raise ValueError('SEC filing columns must be arrays')
    size = len(recent['accessionNumber'])
    if any(len(recent[key]) != size for key in keys):
        raise ValueError('SEC filing columns have inconsistent lengths')
    records = []
    for index in range(size):
        form = recent['form'][index]
        if form not in forms:
            continue
        accession = recent['accessionNumber'][index]
        document = recent['primaryDocument'][index]
        if (not isinstance(accession, str) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession)
                or not isinstance(document, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', document)):
            raise ValueError('SEC filing has an unsafe accession or document name')
        filed = date.fromisoformat(recent['filingDate'][index]).isoformat()
        report = recent['reportDate'][index]
        if report:
            report = date.fromisoformat(report).isoformat()
        accepted = datetime.fromisoformat(recent['acceptanceDateTime'][index].replace('Z', '+00:00'))
        if accepted.tzinfo is None:
            raise ValueError('SEC acceptance timestamp needs a timezone')
        records.append({
            'canonical_url': f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{document}',
            'title': f'{name} — {form} filing ({filed})',
            'published_at': accepted.astimezone(timezone.utc).isoformat(timespec='seconds'),
            'record_type': 'sec_filing',
            'text': f'SEC submission metadata only. Form: {form}; filed: {filed}; reporting period: {report or "not supplied"}; '
                    f'accession: {accession}. The filing text has not been retrieved; this entry establishes the filing, not its business results.'})
    return records
