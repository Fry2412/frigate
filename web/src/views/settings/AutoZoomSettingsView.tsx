import useSWR from "swr";
import { useTranslation } from "react-i18next";
import Heading from "@/components/ui/heading";
import { ConfigSectionTemplate } from "@/components/config-form/sections";
import type { SettingsPageProps } from "./SingleSectionPage";

type PtzInfo = {
  features?: string[];
  autozoom?: { supported: boolean; resolved_mode?: string | null };
};

export default function AutoZoomSettingsView({
  selectedCamera,
  // Profile deletion is handled by the profile editing page. Auto Zoom is a
  // camera-only section, and ConfigSectionTemplate expects a parameterless
  // callback for deleting a section, so do not forward the page-level handler.
  onDeleteProfileSection: _onDeleteProfileSection,
  ...props
}: SettingsPageProps) {
  const { t } = useTranslation(["config/cameras", "views/settings"]);
  const { data: info } = useSWR<PtzInfo>(
    selectedCamera ? `api/${selectedCamera}/ptz/info` : null,
  );
  const zoomSupported = info?.autozoom?.supported;

  if (!selectedCamera) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        {t("configForm.camera.noCameras", { ns: "views/settings" })}
      </div>
    );
  }

  return (
    <div className="flex size-full flex-col lg:pr-2">
      <div className="mb-5 flex flex-col gap-2">
        <Heading as="h4">{t("onvif.autozoom.label")}</Heading>
        <p className="text-sm text-muted-foreground">
          {t("onvif.autozoom.description")}
        </p>
        <div className="rounded-md border border-input bg-muted/30 p-3 text-sm">
          <div className="font-medium">
            {t("autozoom.capabilities", { ns: "views/settings" })}
          </div>
          {info ? (
            <div className="mt-1 text-muted-foreground">
              {t("autozoom.opticalZoom", { ns: "views/settings" })}:{" "}
              {zoomSupported
                ? t("autozoom.supported", { ns: "views/settings" })
                : t("autozoom.notSupported", { ns: "views/settings" })}{" "}
              · {t("autozoom.absolute", { ns: "views/settings" })}:{" "}
              {info.features?.includes("zoom-a")
                ? t("autozoom.supported", { ns: "views/settings" })
                : t("autozoom.notSupported", { ns: "views/settings" })}{" "}
              · {t("autozoom.relative", { ns: "views/settings" })}:{" "}
              {info.features?.includes("zoom-r")
                ? t("autozoom.supported", { ns: "views/settings" })
                : t("autozoom.notSupported", { ns: "views/settings" })}
              {zoomSupported && (
                <>
                  {" "}
                  · {t("autozoom.selectedMode", { ns: "views/settings" })}:{" "}
                  {info.autozoom?.resolved_mode}
                </>
              )}
            </div>
          ) : (
            <div className="mt-1 text-muted-foreground">
              {t("autozoom.checking", { ns: "views/settings" })}
            </div>
          )}
        </div>
        {info && !zoomSupported && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {t("autozoom.unsupported", { ns: "views/settings" })}
          </div>
        )}
      </div>
      <ConfigSectionTemplate
        sectionKey="onvif.autozoom"
        level="camera"
        cameraName={selectedCamera}
        showOverrideIndicator={false}
        onSave={() => props.setUnsavedChanges?.(false)}
        onStatusChange={(status) =>
          props.onSectionStatusChange?.("onvif.autozoom", "camera", status)
        }
        {...props}
      />
    </div>
  );
}
