export type RecognitionSampleStatus =
  | "new"
  | "reviewed"
  | "approved"
  | "training_ready"
  | "excluded";

export interface RecognitionSample {
  id: string;
  detection_crop_id: string;
  model_prediction?: string;
  ground_truth_text?: string;
  confidence?: number;
  status: RecognitionSampleStatus;
  training_enabled: boolean;
  correction_reason?: string;
}

export interface RecognitionGTStudioState {
  samples: RecognitionSample[];
  filter?: RecognitionSampleStatus;
}

export function createRecognitionGTStudioState(samples: RecognitionSample[]): RecognitionGTStudioState {
  return {
    samples,
  };
}
