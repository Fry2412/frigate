/**
 * Vitest: Auto Zoom settings controls in ObjectSettingsView.
 *
 * These tests verify that the Auto Zoom section is properly wired
 * in the ObjectSettingsView and that required translation keys exist
 * for the settings UI.
 *
 * NOTE: Full component render tests require @testing-library/react
 * to be installed. These tests validate i18n key contracts and
 * structural expectations without full DOM rendering.
 */
import { describe, it, expect } from "vitest";

// Verify config translation keys for Auto Zoom settings
describe("Auto Zoom settings i18n keys", () => {
  it("should have auto_zoom config translations", async () => {
    const configTranslations = await import(
      "@/../public/locales/en/config/cameras.json"
    );
    const data =
      configTranslations.default !== undefined
        ? configTranslations.default
        : configTranslations;

    // Navigate to the onvif.auto_zoom section
    const onvif = (data as unknown as Record<string, Record<string, unknown>>)["onvif"];
    expect(onvif).toBeDefined();
    expect(onvif).toHaveProperty("auto_zoom");

    const autoZoom = onvif["auto_zoom"] as Record<string, unknown>;
    expect(autoZoom).toHaveProperty("label");
    expect(autoZoom).toHaveProperty("description");
    expect(autoZoom).toHaveProperty("enabled");
    expect(autoZoom).toHaveProperty("sensitivity");
    expect(autoZoom).toHaveProperty("damping");
    expect(autoZoom).toHaveProperty("target_ratio_min");
    expect(autoZoom).toHaveProperty("target_ratio_max");
    expect(autoZoom).toHaveProperty("edge_margin");
    expect(autoZoom).toHaveProperty("return_to_home_timeout");
    expect(autoZoom).toHaveProperty("manual_override_timeout");
    expect(autoZoom).toHaveProperty("stationary_behavior");
    expect(autoZoom).toHaveProperty("home_zoom_mode");
    expect(autoZoom).toHaveProperty("home_zoom_level");
    expect(autoZoom).toHaveProperty("track");
    expect(autoZoom).toHaveProperty("exclude_zones");
  });

  it("should have label and description for each auto_zoom field", async () => {
    const configTranslations = await import(
      "@/../public/locales/en/config/cameras.json"
    );
    const data =
      configTranslations.default !== undefined
        ? configTranslations.default
        : configTranslations;

    const onvif = (data as unknown as Record<string, Record<string, unknown>>)["onvif"];
    const autoZoom = (onvif as unknown as Record<string, Record<string, unknown>>)[
      "auto_zoom"
    ];

    const fieldsWithLabelDesc = [
      "enabled",
      "sensitivity",
      "damping",
      "target_ratio_min",
      "target_ratio_max",
      "edge_margin",
      "return_to_home_timeout",
      "manual_override_timeout",
      "stationary_behavior",
      "home_zoom_mode",
      "home_zoom_level",
    ];

    for (const field of fieldsWithLabelDesc) {
      const fieldObj = autoZoom[field] as Record<string, string>;
      expect(fieldObj, `${field} should exist`).toBeDefined();
      expect(fieldObj.label, `${field}.label should exist`).toBeDefined();
      expect(
        fieldObj.description,
        `${field}.description should exist`,
      ).toBeDefined();
    }
  });

  it("should have autoZoomCapable key in settings translations", async () => {
    const settingsTranslations = await import(
      "@/../public/locales/en/views/settings.json"
    );
    const data =
      settingsTranslations.default !== undefined
        ? settingsTranslations.default
        : settingsTranslations;

    // Navigate to cameraWizard.step2 section where probe results live
    const cameraWizard = (
      data as unknown as Record<string, Record<string, unknown>>
    )["cameraWizard"];
    expect(cameraWizard).toBeDefined();

    const step2 = cameraWizard["step2"] as Record<string, string>;
    expect(step2).toBeDefined();
    expect(step2).toHaveProperty("autoZoomCapable");
  });
});

// Verify Auto Zoom config type module loads correctly
describe("Auto Zoom config type structure", () => {
  it("should successfully import frigateConfig types module", async () => {
    const configTypes = await import("@/types/frigateConfig");
    expect(configTypes).toBeDefined();
    // Module should load without errors — TypeScript interfaces are erased at
    // runtime, so we verify the module itself is importable (compile-time
    // type safety is enforced by tsc, not runtime assertions).
    expect(typeof configTypes).toBe("object");
  });
});
