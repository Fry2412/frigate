type PtzFeature =
  | "pt"
  | "zoom"
  | "pt-r"
  | "zoom-r"
  | "zoom-a"
  | "pt-r-fov"
  | "focus";

export type OnvifProfile = {
  name: string;
  token: string;
};

export type CameraPtzInfo = {
  name: string;
  features: PtzFeature[];
  presets: string[];
  profiles: OnvifProfile[];
};

// Auto Zoom capability and support types

export type AutoZoomSupportClass =
  | "none"
  | "zoom_only"
  | "full_ptz"
  | "limited";

export type AutoZoomSupportStatus =
  | "supported"
  | "degraded"
  | "unsupported";

export type AutoZoomCapabilityInfo = {
  zoom_supported: boolean;
  absolute_zoom_supported: boolean;
  relative_zoom_supported: boolean;
  support_class: AutoZoomSupportClass;
  support_status: AutoZoomSupportStatus;
  unsupported_reason?: string;
};

// Auto Zoom runtime state

export type AutoZoomState =
  | "off"
  | "ready"
  | "tracking"
  | "holding"
  | "returning_home"
  | "paused_manual"
  | "suspended";

export type AutoZoomLastAction =
  | "zoom_in"
  | "zoom_out"
  | "hold"
  | "return_home"
  | "none";

export type AutoZoomRuntimeInfo = {
  enabled: boolean;
  state: AutoZoomState;
  active: boolean;
  target_class?: string;
  target_id?: string;
  last_reason?: string;
  last_suppression_reason?: string;
  manual_pause_until?: number;
  support_status: AutoZoomSupportStatus;
};
