import type { SectionConfigOverrides } from "./types";

const autozoom: SectionConfigOverrides = {
  base: {
    sectionDocs: "/configuration/autotracking#object-auto-zoom",
    fieldOrder: [
      "enabled",
      "mode",
      "track",
      "required_zones",
      "framing",
      "zoom",
      "tracking",
      "return",
    ],
    advancedFields: [
      "tracking",
      "zoom.min",
      "zoom.zoom_in_step",
      "zoom.zoom_out_step",
      "zoom.emergency_zoom_out_step",
      "framing.emergency_margin",
    ],
    restartRequired: [],
    uiSchema: {
      track: { "ui:widget": "objectLabels" },
      required_zones: { "ui:widget": "zoneNames" },
      framing: { preset: { "ui:widget": "select" } },
    },
    messages: [
      {
        key: "autozoom-ptz-conflict",
        messageKey: "autozoomPtzConflict",
        severity: "error",
        condition: ({ fullCameraConfig }) =>
          !!fullCameraConfig?.onvif?.autotracking?.enabled,
      },
    ],
  },
};

export default autozoom;
