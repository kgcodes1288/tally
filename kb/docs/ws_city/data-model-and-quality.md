# NYC 311 service requests: model and data quality

311 is New York City's non-emergency service line. Each row in `service_requests` is one request created between 1 January and 31 March 2025, with the city agency that handled it (for example NYPD for noise, HPD for heat and hot water, DSNY for sanitation).

## Key columns
- `created_date`, `closed_date`: when the request was opened and closed. `closed_date` is empty while open.
- `response_hours`: closed minus created, in hours (derived by Tally).
- `complaint_type`, `descriptor`: what the request is about, from general to specific.
- `agency`, `agency_name`: the responsible city agency.
- `borough`, `incident_zip`, `community_board`, `latitude`, `longitude`: where it happened.
- `open_data_channel_type`: how it was reported (phone, online, mobile app).
- `status`, `resolution_description`: current state and the agency's closing note.

## Known data-quality issues to check
- **Negative response times**: some requests are closed before they were created. Exclude them from averages and report the count.
- **Missing borough**: recorded as `UNSPECIFIED`. Only the citywide persona can see these.
- **Open requests**: requests with no `closed_date` must be excluded from response-time averages, but counted as backlog.
- **Very long response times** (for example over 60 days) are worth reporting separately, not averaging in silently.
- Prefer the median over the mean for response times; the distribution is heavily skewed.

## Reporting conventions
- Always state the date range and which boroughs the requester can see.
- Show response times as median and 90th percentile, by complaint type and agency.
