/* Recognition GT Studio.
 *
 * This is intentionally separate from Detection GT.
 * Detection GT teaches the detector where regions are.
 * Recognition GT teaches the recognition model what text/value a crop contains.
 */

declare const React: any;

const h = React.createElement;

export type RecognitionReviewStatus =
  | "new"
  | "reviewing"
  | "corrected"
  | "approved"
  | "training_ready";

export interface RecognitionSample {
  id: string;
  cropPath: string;
  detectedText?: string;
  groundTruthText: string;
  field?: string;
  status: RecognitionReviewStatus;
  includeInTraining: boolean;
}

export interface RecognitionGTStudioState {
  samples: RecognitionSample[];
  activeIndex: number;
}

export function RecognitionGTStudio(props: {
  sample?: RecognitionSample;
  onApprove?: () => void;
  onNext?: () => void;
  onPrevious?: () => void;
}) {
  const sample = props.sample;

  return h(
    "section",
    { className: "recognition-gt-studio" },
    h("h2", null, "Recognition GT Studio"),
    h(
      "p",
      null,
      "Review recognition ground truth independently from detection annotations."
    ),
    sample
      ? h(
          "div",
          null,
          h("div", { className: "crop-viewer" }, sample.cropPath),
          h("div", null, "Detection output: ", sample.detectedText || ""),
          h("div", null, "Recognition GT: ", sample.groundTruthText),
          h("div", null, "Status: ", sample.status),
          h(
            "button",
            { onClick: props.onApprove },
            "Approve recognition GT"
          )
        )
      : h("div", null, "No recognition sample selected"),
    h(
      "nav",
      null,
      h("button", { onClick: props.onPrevious }, "Previous"),
      h("button", { onClick: props.onNext }, "Next")
    )
  );
}
