# IsalaOCR Model Factory - Detection and Recognition Workflow

## Separation

Detection and Recognition are independent ML pipelines.

## Detection

Purpose: determine where information exists.

Flow:

Images -> Detection GT Studio -> Detection Dataset -> Detection Model -> Detection Evaluation -> Detection GT improvement

Detection GT contains only geometry and structure:

- regions
- tables
- panels
- cells
- text blocks
- crops

No text content is stored as detection truth.

## Recognition

Purpose: determine the content of a detected region.

Flow:

Detection crop -> Recognition GT Studio -> Recognition Dataset -> Recognition Model -> Recognition Evaluation -> GT improvement

Recognition owns:

- text truth
- value truth
- prediction comparison
- correction reason
- training selection

## Model responsibility

Detection errors:
- wrong location
- wrong crop
- wrong structure

Recognition errors:
- wrong text
- wrong value
- wrong interpretation

The two models must be evaluated separately.
