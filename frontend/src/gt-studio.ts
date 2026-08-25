/* Ground Truth Studio review workflow. */

declare const React: any;
declare const ReactDOM: any;
declare const window: any;

const h = React.createElement;

type GTReviewStatus =
  | "new"
  | "reviewing"
  | "corrected"
  | "approved"
  | "training_ready";

interface GTImageReview {
  image_id: string;
  image_url?: string;
  status: GTReviewStatus;
  included_for_training: boolean;
  annotations: Array<{
    id: string;
    type: string;
    x: number;
    y: number;
    width: number;
    height: number;
    source: "detection" | "ground_truth";
  }>;
}

interface GTStudioProps {
  image?: GTImageReview | null;
  onPrevious?: () => void;
  onNext?: () => void;
  onApprove?: () => void;
  onToggleTraining?: () => void;
}

function GTStudio(props: GTStudioProps) {
  const image = props.image;

  return h(
    "section",
    { className: "gt-studio" },
    h("header", null,
      h("h2", null, "GT Studio / Review Studio"),
      h("span", null, image ? image.status : "no image")
    ),
    h("div", { className: "gt-studio-layout" },
      h("div", { className: "gt-viewer" },
        image?.image_url
          ? h("img", { src: image.image_url, alt: "Ground truth review" })
          : h("div", null, "Image viewer")
      ),
      h("aside", { className: "gt-controls" },
        h("button", { onClick: props.onPrevious }, "Previous"),
        h("button", { onClick: props.onNext }, "Next"),
        h("button", { onClick: props.onApprove }, "Approve GT"),
        h("button", { onClick: props.onToggleTraining }, "Toggle training")
      )
    )
  );
}

const bootstrap = window.__ISALA_GT_STUDIO__;
const root = document.getElementById("gt-studio-root");
if (root && bootstrap) {
  ReactDOM.render(
    h(GTStudio, {
      image: bootstrap.image,
      onPrevious: bootstrap.previous,
      onNext: bootstrap.next,
      onApprove: bootstrap.approve,
      onToggleTraining: bootstrap.toggleTraining,
    }),
    root,
  );
}
