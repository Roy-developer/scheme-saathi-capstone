# Frontend prototype contract

Status: provisional; Roles 1, 3 and 4 must review the later domain and service
contracts.

The first deployed frontend is a synthetic demonstration. It does not evaluate
eligibility, collect real personal data, contact a government service or submit
an application.

## Initial shell

The first revision provides:

- a persistent synthetic-demonstration warning;
- English, Hindi and Marathi presentation;
- an application version supplied through `APP_VERSION`;
- a container health endpoint supplied by Streamlit.

## Invariants

1. The warning must remain visible in every language.
2. No secrets or real personal information may be placed in the image.
3. The frontend must not claim to determine eligibility.
4. Future fixture responses must include clause, source URL and collection date.
5. Future backend state must remain outside Streamlit session state.

## Replacement path

The next frontend revision will use explicitly synthetic fixture responses.
Those responses will later be replaced by versioned FastAPI contracts without
changing the user journey.
