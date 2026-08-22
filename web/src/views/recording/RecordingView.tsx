import ReviewCard from "@/components/card/ReviewCard";
import ReviewFilterGroup from "@/components/filter/ReviewFilterGroup";
import DebugReplayDialog from "@/components/overlay/DebugReplayDialog";
import ExportDialog from "@/components/overlay/ExportDialog";
import ActionsDropdown from "@/components/overlay/ActionsDropdown";
import PreviewPlayer, {
  PreviewController,
} from "@/components/player/PreviewPlayer";
import { DynamicVideoController } from "@/components/player/dynamic/DynamicVideoController";
import DynamicVideoPlayer from "@/components/player/dynamic/DynamicVideoPlayer";
import MotionReviewTimeline from "@/components/timeline/MotionReviewTimeline";
import DetailStream from "@/components/timeline/DetailStream";
import ReviewTimeline from "@/components/timeline/ReviewTimeline";
import {
  VirtualizedMotionSegments,
  VirtualizedMotionSegmentsRef,
} from "@/components/timeline/VirtualizedMotionSegments";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useOverlayState } from "@/hooks/use-overlay-state";
import { useResizeObserver } from "@/hooks/resize-observer";
import { ExportMode } from "@/types/filter";
import { FrigateConfig } from "@/types/frigateConfig";
import { Preview } from "@/types/preview";
import {
  MotionData,
  RecordingsSummary,
  REVIEW_PADDING,
  ReviewFilter,
  ReviewSegment,
  ReviewSummary,
  TimelineZoomDirection,
  ZoomLevel,
} from "@/types/review";
import { getChunkedTimeDay } from "@/utils/timelineUtil";
import {
  MutableRefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  isDesktop,
  isMobile,
  isMobileOnly,
  isTablet,
} from "react-device-detect";
import { IoMdArrowRoundBack } from "react-icons/io";
import { useNavigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import useSWR from "swr";
import { TimeRange, TimelineType } from "@/types/timeline";
import MobileCameraDrawer from "@/components/overlay/MobileCameraDrawer";
import MobileTimelineDrawer from "@/components/overlay/MobileTimelineDrawer";
import MobileReviewSettingsDrawer from "@/components/overlay/MobileReviewSettingsDrawer";
import Logo from "@/components/Logo";
import { Skeleton } from "@/components/ui/skeleton";
import { FaVideo } from "react-icons/fa";
import { VideoResolutionType } from "@/types/live";
import {
  ASPECT_VERTICAL_LAYOUT,
  ASPECT_WIDE_LAYOUT,
  RecordingSegment,
  RecordingStartingPoint,
} from "@/types/record";
import { cn } from "@/lib/utils";
import { useFullscreen } from "@/hooks/use-fullscreen";
import { useTimezone } from "@/hooks/use-date-utils";
import { useTimelineZoom } from "@/hooks/use-timeline-zoom";
import { useTranslation } from "react-i18next";
import { useTimelineUtils } from "@/hooks/use-timeline-utils";
import { useMotionSegmentUtils } from "@/hooks/use-motion-segment-utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { CameraNameLabel } from "@/components/camera/FriendlyNameLabel";
import { useAllowedCameras } from "@/hooks/use-allowed-cameras";
import { DetailStreamProvider } from "@/context/detail-stream-context";
import {
  GenAISummaryDialog,
  GenAISummaryChip,
} from "@/components/overlay/chip/GenAISummaryChip";

const DATA_REFRESH_TIME = 600000; // 10 minutes

type RecordingViewProps = {
  startCamera: string;
  startTime: number;
  reviewItems?: ReviewSegment[];
  reviewSummary?: ReviewSummary;
  timeRange: TimeRange;
  allCameras: string[];
  allPreviews?: Preview[];
  filter?: ReviewFilter;
  updateFilter: (newFilter: ReviewFilter) => void;
  refreshData?: () => void;
};
export function RecordingView({
  startCamera,
  startTime,
  reviewItems,
  reviewSummary,
  timeRange,
  allCameras,
  allPreviews,
  filter,
  updateFilter,
  refreshData,
}: RecordingViewProps) {
  const { t } = useTranslation(["views/events"]);
  const { data: config } = useSWR<FrigateConfig>("config");
  const navigate = useNavigate();
  const contentRef = useRef<HTMLDivElement | null>(null);

  // recordings summary

  const timezone = useTimezone(config);

  const allowedCameras = useAllowedCameras();
  const effectiveCameras = useMemo(
    () => allCameras.filter((camera) => allowedCameras.includes(camera)),
    [allCameras, allowedCameras],
  );
  const [mainCamera, setMainCamera] = useState(startCamera);
  const [multicamCameras, setMulticamCameras] = useState<string[]>([
    startCamera,
  ]);
  const isMulticam = multicamCameras.length > 1;
  const [activeControlsCamera, setActiveControlsCamera] =
    useState(startCamera);

  const { data: recordingsSummary } = useSWR<RecordingsSummary>([
    "recordings/summary",
    {
      timezone: timezone,
      cameras: mainCamera ?? null,
    },
  ]);

  // controller state

  const mainControllerRef = useRef<DynamicVideoController | null>(null);
  const multicamControllerRefs = useRef<
    Record<string, DynamicVideoController>
  >({});
  const mainLayoutRef = useRef<HTMLDivElement | null>(null);
  const cameraLayoutRef = useRef<HTMLDivElement | null>(null);
  const previewRowRef = useRef<HTMLDivElement | null>(null);
  const previewRefs = useRef<{ [camera: string]: PreviewController }>({});

  const [playbackStart, setPlaybackStart] = useState(
    startTime >= timeRange.after && startTime <= timeRange.before
      ? startTime
      : timeRange.before - 60,
  );

  const mainCameraReviewItems = useMemo(
    () => reviewItems?.filter((cam) => cam.camera == mainCamera) ?? [],
    [reviewItems, mainCamera],
  );

  // timeline

  const [recording] = useOverlayState<RecordingStartingPoint>(
    "recording",
    undefined,
    false,
  );

  const [timelineType, setTimelineType] = useOverlayState<TimelineType>(
    "timelineType",
    recording?.timelineType ?? "timeline",
  );

  const chunkedTimeRange = useMemo(
    () => getChunkedTimeDay(timeRange),
    [timeRange],
  );
  const [selectedRangeIdx, setSelectedRangeIdx] = useState(
    chunkedTimeRange.findIndex((chunk) => {
      return chunk.after <= startTime && chunk.before >= startTime;
    }),
  );
  const currentTimeRange = useMemo<TimeRange>(
    () =>
      chunkedTimeRange[selectedRangeIdx] ??
      chunkedTimeRange[chunkedTimeRange.length - 1],
    [selectedRangeIdx, chunkedTimeRange],
  );

  const reviewFilterList = useMemo(() => {
    const uniqueLabels = new Set<string>();

    reviewItems?.forEach((rev) => {
      rev.data.objects.forEach((obj) =>
        uniqueLabels.add(obj.replace("-verified", "")),
      );
      rev.data.audio.forEach((aud) => uniqueLabels.add(aud));
    });

    const uniqueZones = new Set<string>();

    reviewItems?.forEach((rev) => {
      rev.data.zones.forEach((zone) => uniqueZones.add(zone));
    });

    return { labels: [...uniqueLabels], zones: [...uniqueZones] };
  }, [reviewItems]);

  // export

  const [exportMode, setExportMode] = useState<ExportMode>("none");
  const [exportRange, setExportRange] = useState<TimeRange>();
  const [showExportPreview, setShowExportPreview] = useState(false);

  // debug replay

  const [debugReplayMode, setDebugReplayMode] = useState<ExportMode>("none");
  const [debugReplayRange, setDebugReplayRange] = useState<TimeRange>();

  // move to next clip

  const onClipEnded = useCallback(() => {
    if (!mainControllerRef.current) {
      return;
    }

    if (selectedRangeIdx < chunkedTimeRange.length - 1) {
      setSelectedRangeIdx(selectedRangeIdx + 1);
    }
  }, [selectedRangeIdx, chunkedTimeRange]);

  // visibility tracking for refreshing stale data

  const lastVisibilityTime = useRef<number>(Date.now());

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        const now = Date.now();
        const timeSinceLastVisible = now - lastVisibilityTime.current;

        // Only refresh if user was away for a while
        // and the video is not currently playing
        if (
          timeSinceLastVisible >= DATA_REFRESH_TIME &&
          refreshData &&
          mainControllerRef.current &&
          !mainControllerRef.current.isPlaying()
        ) {
          refreshData();
        }

        lastVisibilityTime.current = now;
      } else {
        lastVisibilityTime.current = Date.now();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [refreshData]);

  // scrubbing and timeline state

  const [scrubbing, setScrubbing] = useState(false);
  const [currentTime, setCurrentTime] = useState<number>(startTime);
  const [playerTime, setPlayerTime] = useState(startTime);
  const [isPlaybackPlaying, setIsPlaybackPlaying] = useState(true);

  const synchronizeMulticam = useCallback(
    (timestamp: number, playing: boolean, sourceCamera?: string) => {
      Object.entries(multicamControllerRefs.current).forEach(
        ([camera, controller]) => {
          if (camera !== sourceCamera) {
            controller.synchronizeToTimestamp(timestamp, playing);
          }
        },
      );
    },
    [],
  );

  const handleMasterTimestampUpdate = useCallback(
    (timestamp: number) => {
      setPlayerTime(timestamp);
      setCurrentTime(timestamp);
      Object.values(previewRefs.current ?? {}).forEach((prev) =>
        prev.scrubToTimestamp(Math.floor(timestamp)),
      );
      synchronizeMulticam(
        timestamp,
        mainControllerRef.current?.isPlaying() ?? isPlaybackPlaying,
        mainCamera,
      );
    },
    [isPlaybackPlaying, mainCamera, synchronizeMulticam],
  );

  const handlePlaybackStateChange = useCallback(
    (playing: boolean, sourceCamera: string = mainCamera) => {
      setIsPlaybackPlaying(playing);
      synchronizeMulticam(currentTime, playing, sourceCamera);
    },
    [currentTime, mainCamera, synchronizeMulticam],
  );

  const handlePlaybackRateChange = useCallback((rate: number) => {
    Object.values(multicamControllerRefs.current).forEach((controller) =>
      controller.setPlaybackRate(rate),
    );
  }, []);

  const updateSelectedSegment = useCallback(
    (currentTime: number, updateStartTime: boolean) => {
      const index = chunkedTimeRange.findIndex(
        (seg) => seg.after <= currentTime && seg.before >= currentTime,
      );

      if (index != -1) {
        if (updateStartTime) {
          setPlaybackStart(currentTime);
        }

        setSelectedRangeIdx(index);
      }
    },
    [chunkedTimeRange],
  );

  useEffect(() => {
    if (scrubbing || exportRange || debugReplayRange) {
      if (
        currentTime > currentTimeRange.before + 60 ||
        currentTime < currentTimeRange.after - 60
      ) {
        updateSelectedSegment(currentTime, false);
        return;
      }

      Object.values(multicamControllerRefs.current).forEach((controller) =>
        controller.scrubToTimestamp(currentTime, true),
      );

      Object.values(previewRefs.current).forEach((controller) => {
        controller.scrubToTimestamp(currentTime);
      });
    }
    // we only want to seek when current time updates
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    currentTime,
    scrubbing,
    timeRange,
    currentTimeRange,
    updateSelectedSegment,
  ]);

  const manuallySetCurrentTime = useCallback(
    (time: number, play: boolean = false) => {
      if (!currentTimeRange) {
        return;
      }
      setCurrentTime(time);

      if (currentTimeRange.after <= time && currentTimeRange.before >= time) {
        Object.values(multicamControllerRefs.current).forEach((controller) =>
          controller.seekToTimestamp(time, play),
        );
      } else {
        updateSelectedSegment(time, true);
      }
    },
    [currentTimeRange, updateSelectedSegment],
  );

  useEffect(() => {
    if (!scrubbing) {
      if (Math.abs(currentTime - playerTime) > 10) {
        if (
          currentTimeRange.after <= currentTime &&
          currentTimeRange.before >= currentTime
        ) {
          if (mainControllerRef.current != undefined) {
            let shouldPlayback = true;

            if (timelineType == "detail") {
              shouldPlayback = mainControllerRef.current.isPlaying();
            }

            Object.values(multicamControllerRefs.current).forEach(
              (controller) =>
                controller.seekToTimestamp(currentTime, shouldPlayback),
            );
          }
        } else {
          updateSelectedSegment(currentTime, true);
        }
      } else if (playerTime != currentTime && timelineType != "detail") {
        mainControllerRef.current?.play();
      }
    }
    // we only want to seek when current time doesn't match the player update time
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentTime, scrubbing]);

  const [fullResolution, setFullResolution] = useState<VideoResolutionType>({
    width: 0,
    height: 0,
  });

  const onSelectCamera = useCallback(
    (newCam: string) => {
      if (allowedCameras.includes(newCam)) {
        setMainCamera(newCam);
        setMulticamCameras([newCam]);
        setActiveControlsCamera(newCam);
        setFullResolution({
          width: 0,
          height: 0,
        });
        setPlaybackStart(currentTime);
      }
    },
    [currentTime, allowedCameras],
  );

  const onMulticamSelectionChange = useCallback(
    (value: string[]) => {
      const next = value.filter((camera) => camera !== "birdseye");

      if (next.length === 0) {
        return;
      }

      setMulticamCameras(next);

      if (!next.includes(mainCamera)) {
        setMainCamera(next[0]);
      }

      if (!next.includes(activeControlsCamera)) {
        setActiveControlsCamera(next[0]);
      }
    },
    [activeControlsCamera, mainCamera],
  );

  const activateMulticamCamera = useCallback((camera: string) => {
    setActiveControlsCamera(camera);
    setMainCamera(camera);
    setMulticamCameras((current) => [
      camera,
      ...current.filter((item) => item !== camera),
    ]);
  }, []);

  const ignoreFullResolution = useCallback(
    (_resolution: React.SetStateAction<VideoResolutionType>) => undefined,
    [],
  );

  useEffect(() => {
    mainControllerRef.current =
      multicamControllerRefs.current[mainCamera] ?? null;
  }, [mainCamera, multicamCameras]);

  useEffect(() => {
    Object.keys(multicamControllerRefs.current).forEach((camera) => {
      if (!multicamCameras.includes(camera)) {
        delete multicamControllerRefs.current[camera];
      }
    });
  }, [multicamCameras]);

  // fullscreen

  const { fullscreen, toggleFullscreen, supportsFullScreen } =
    useFullscreen(mainLayoutRef);

  // layout

  const getCameraAspect = useCallback(
    (cam: string) => {
      if (!config) {
        return undefined;
      }

      if (cam == mainCamera && fullResolution.width && fullResolution.height) {
        return fullResolution.width / fullResolution.height;
      }

      const camera = config.cameras[cam];

      if (!camera) {
        return undefined;
      }

      return camera.detect.width / camera.detect.height;
    },
    [config, fullResolution, mainCamera],
  );

  const mainCameraAspect = useMemo(() => {
    const aspectRatio = getCameraAspect(mainCamera);

    if (!aspectRatio) {
      return "normal";
    } else if (aspectRatio > ASPECT_WIDE_LAYOUT) {
      return "wide";
    } else if (aspectRatio < ASPECT_VERTICAL_LAYOUT) {
      return "tall";
    } else {
      return "normal";
    }
  }, [getCameraAspect, mainCamera]);

  // The surrounding camera tile already owns the camera aspect ratio. Keep
  // the player itself at the exact tile size so the video element can fit its
  // source with object-contain instead of introducing a second aspect ratio.
  const grow = "size-full min-h-0 min-w-0";

  const multicamGridClass = useMemo(() => {
    if (isDesktop) {
      if (multicamCameras.length === 2) {
        return "grid-cols-2 grid-rows-1";
      }

      if (multicamCameras.length === 3) {
        return "grid-cols-2 grid-rows-2";
      }

      if (multicamCameras.length === 4) {
        return "grid-cols-2 grid-rows-2";
      }

      return "grid-cols-3 auto-rows-fr";
    }

    if (multicamCameras.length === 2) {
      return "portrait:grid-cols-1 portrait:grid-rows-2 landscape:grid-cols-2 landscape:grid-rows-1";
    }

    if (multicamCameras.length === 3) {
      return "portrait:grid-cols-2 portrait:grid-rows-2 landscape:grid-cols-3 landscape:grid-rows-1";
    }

    return "grid-cols-2 auto-rows-fr landscape:grid-cols-3";
  }, [multicamCameras.length]);

  // use a resize observer to determine whether to use w-full or h-full based on container aspect ratio
  const [{ width: containerWidth, height: containerHeight }] =
    useResizeObserver(cameraLayoutRef);
  const [{ width: previewRowWidth, height: previewRowHeight }] =
    useResizeObserver(previewRowRef);

  const useHeightBased = useMemo(() => {
    if (!containerWidth || !containerHeight) {
      return false;
    }

    const cameraAspectRatio = getCameraAspect(mainCamera);
    if (!cameraAspectRatio) {
      return false;
    }

    // Calculate available space for camera after accounting for preview row
    // For tall cameras: preview row is side-by-side (takes width)
    // For wide/normal cameras: preview row is stacked (takes height)
    const availableWidth =
      mainCameraAspect == "tall" && previewRowWidth
        ? containerWidth - previewRowWidth
        : containerWidth;
    const availableHeight =
      mainCameraAspect != "tall" && previewRowHeight
        ? containerHeight - previewRowHeight
        : containerHeight;

    const availableAspectRatio = availableWidth / availableHeight;

    // If available space is wider than camera aspect, constrain by height (h-full)
    // If available space is taller than camera aspect, constrain by width (w-full)
    return availableAspectRatio >= cameraAspectRatio;
  }, [
    containerWidth,
    containerHeight,
    previewRowWidth,
    previewRowHeight,
    getCameraAspect,
    mainCamera,
    mainCameraAspect,
  ]);

  const previewRowOverflows = useMemo(() => {
    if (!previewRowRef.current) {
      return false;
    }

    return (
      previewRowRef.current.scrollWidth > previewRowRef.current.clientWidth ||
      previewRowRef.current.scrollHeight > previewRowRef.current.clientHeight
    );
    // we only want to update when the scroll size changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewRowRef.current?.scrollWidth, previewRowRef.current?.scrollHeight]);

  // visibility listener for lazy loading

  const [visiblePreviews, setVisiblePreviews] = useState<string[]>([]);
  const visiblePreviewObserver = useRef<IntersectionObserver | null>(null);
  useEffect(() => {
    const visibleCameras = new Set<string>();
    visiblePreviewObserver.current = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const camera = (entry.target as HTMLElement).dataset.camera;

          if (!camera) {
            return;
          }

          if (entry.isIntersecting) {
            visibleCameras.add(camera);
          } else {
            visibleCameras.delete(camera);
          }

          setVisiblePreviews([...visibleCameras]);
        });
      },
      { threshold: 0.1 },
    );

    return () => {
      visiblePreviewObserver.current?.disconnect();
    };
  }, []);

  const previewRef = useCallback(
    (node: HTMLElement | null) => {
      if (!visiblePreviewObserver.current) {
        return;
      }

      try {
        if (node) visiblePreviewObserver.current.observe(node);
      } catch (e) {
        // no op
      }
    },
    // we need to listen on the value of the ref
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visiblePreviewObserver.current],
  );

  const activeReviewItem = useMemo(() => {
    if (!config?.cameras?.[mainCamera].review.genai?.enabled_in_config) {
      return undefined;
    }

    return mainCameraReviewItems.find(
      (rev) =>
        rev.start_time - REVIEW_PADDING < currentTime &&
        rev.end_time &&
        currentTime < rev.end_time + REVIEW_PADDING,
    );
  }, [config, currentTime, mainCameraReviewItems, mainCamera]);
  const onAnalysisOpen = useCallback(
    (open: boolean) => {
      if (open) {
        mainControllerRef.current?.pause();
      } else {
        mainControllerRef.current?.play();
      }
    },
    [mainControllerRef],
  );

  return (
    <DetailStreamProvider
      isDetailMode={timelineType === "detail"}
      currentTime={currentTime}
      camera={mainCamera}
    >
      <div ref={contentRef} className="flex size-full flex-col pt-2">
        <Toaster closeButton={true} />
        <div className="relative mb-2 flex h-11 w-full items-center justify-between px-2">
          {isMobile && (
            <Logo className="absolute inset-x-1/2 h-8 -translate-x-1/2" />
          )}
          <div className={cn("flex items-center gap-2")}>
            <Button
              className="flex items-center gap-2.5 rounded-lg"
              aria-label={t("label.back", { ns: "common" })}
              size="sm"
              onClick={() => navigate(-1)}
            >
              <IoMdArrowRoundBack className="size-5 text-secondary-foreground" />
              {isDesktop && (
                <div className="text-primary">
                  {t("button.back", { ns: "common" })}
                </div>
              )}
            </Button>
            <Button
              className="flex items-center gap-2.5 rounded-lg"
              aria-label="Go to the main camera live view"
              size="sm"
              onClick={() => {
                navigate(`/#${mainCamera}`);
              }}
            >
              <FaVideo className="size-5 text-secondary-foreground" />
              {isDesktop && (
                <div className="text-primary">
                  {t("menu.live.title", { ns: "common" })}
                </div>
              )}
            </Button>
          </div>
          <div className="flex items-center justify-end gap-2">
            <MobileCameraDrawer
              allCameras={effectiveCameras}
              selected={mainCamera}
              onSelectCamera={onSelectCamera}
            />
            {isDesktop && effectiveCameras.length > 1 && (
              <ToggleGroup
                type="multiple"
                value={multicamCameras}
                onValueChange={onMulticamSelectionChange}
                aria-label={t("multicam.selectCameras", {
                  defaultValue: "Select cameras for multi-camera playback",
                })}
                className="max-w-[min(52vw,32rem)] overflow-x-auto scrollbar-container"
              >
                {effectiveCameras
                  .filter((camera) => camera !== "birdseye")
                  .map((camera) => (
                    <ToggleGroupItem
                      key={camera}
                      value={camera}
                      size="sm"
                      className="max-w-40 truncate rounded-md px-2 py-1 text-xs"
                      aria-label={t("multicam.toggleCamera", {
                        defaultValue: "Toggle camera {{camera}}",
                        camera,
                      })}
                    >
                      <CameraNameLabel camera={camera} />
                    </ToggleGroupItem>
                  ))}
              </ToggleGroup>
            )}
            {isDesktop && (
              <DebugReplayDialog
                camera={mainCamera}
                currentTime={currentTime}
                latestTime={timeRange.before}
                mode={debugReplayMode}
                range={debugReplayRange}
                setRange={(range: TimeRange | undefined) => {
                  setDebugReplayRange(range);

                  if (range != undefined) {
                    mainControllerRef.current?.pause();
                  }
                }}
                setMode={setDebugReplayMode}
              />
            )}
            {isDesktop && (
              <ExportDialog
                camera={mainCamera}
                currentTime={currentTime}
                latestTime={timeRange.before}
                mode={exportMode}
                range={exportRange}
                showPreview={showExportPreview}
                setRange={(range) => {
                  setExportRange(range);

                  if (range != undefined) {
                    mainControllerRef.current?.pause();
                  }
                }}
                setMode={setExportMode}
                setShowPreview={setShowExportPreview}
              />
            )}
            {isDesktop && (
              <ReviewFilterGroup
                filters={["cameras", "date", "general"]}
                reviewSummary={reviewSummary}
                recordingsSummary={recordingsSummary}
                filter={filter}
                motionOnly={false}
                filterList={reviewFilterList}
                showReviewed
                setShowReviewed={() => {}}
                mainCamera={mainCamera}
                onUpdateFilter={(newFilter: ReviewFilter) => {
                  const updatedCameras =
                    newFilter.cameras === undefined
                      ? undefined // Respect undefined as "all cameras"
                      : newFilter.cameras
                        ? Array.from(
                            new Set([mainCamera, ...(newFilter.cameras || [])]),
                          ) // Include mainCamera if specific cameras are selected
                        : [mainCamera];
                  const adjustedFilter: ReviewFilter = {
                    ...newFilter,
                    cameras: updatedCameras,
                  };
                  updateFilter(adjustedFilter);
                }}
                setMotionOnly={() => {}}
              />
            )}
            {isDesktop && (
              <ActionsDropdown
                onDebugReplayClick={() => {
                  const now = new Date(timeRange.before * 1000);
                  now.setHours(now.getHours() - 1);
                  setDebugReplayRange({
                    after: now.getTime() / 1000,
                    before: timeRange.before,
                  });
                  setDebugReplayMode("select");
                }}
                onExportClick={() => {
                  const now = new Date(timeRange.before * 1000);
                  now.setHours(now.getHours() - 1);
                  setExportRange({
                    before: timeRange.before,
                    after: now.getTime() / 1000,
                  });
                  setExportMode("select");
                }}
              />
            )}
            {isDesktop ? (
              <ToggleGroup
                className="*:rounded-md *:px-3 *:py-4"
                type="single"
                size="sm"
                value={timelineType}
                onValueChange={(value: TimelineType) =>
                  value ? setTimelineType(value, true) : null
                } // don't allow the severity to be unselected
              >
                <ToggleGroupItem
                  className={`${timelineType == "timeline" ? "" : "text-muted-foreground"}`}
                  value="timeline"
                  aria-label={t("timeline.aria")}
                >
                  <div className="">{t("timeline.label")}</div>
                </ToggleGroupItem>
                <ToggleGroupItem
                  className={`${timelineType == "events" ? "" : "text-muted-foreground"}`}
                  value="events"
                  aria-label={t("events.aria")}
                >
                  <div className="">{t("events.label")}</div>
                </ToggleGroupItem>
                <ToggleGroupItem
                  className={`${timelineType == "detail" ? "" : "text-muted-foreground"}`}
                  value="detail"
                  aria-label="Detail Stream"
                >
                  <div className="">{t("detail.label")}</div>
                </ToggleGroupItem>
              </ToggleGroup>
            ) : (
              <MobileTimelineDrawer
                selected={timelineType ?? "timeline"}
                onSelect={setTimelineType}
              />
            )}
            <MobileReviewSettingsDrawer
              camera={mainCamera}
              filter={filter}
              currentTime={currentTime}
              latestTime={timeRange.before}
              recordingsSummary={recordingsSummary}
              mode={exportMode}
              range={exportRange}
              showExportPreview={showExportPreview}
              allLabels={reviewFilterList.labels}
              allZones={reviewFilterList.zones}
              debugReplayMode={debugReplayMode}
              debugReplayRange={debugReplayRange}
              setDebugReplayMode={setDebugReplayMode}
              setDebugReplayRange={(range: TimeRange | undefined) => {
                setDebugReplayRange(range);

                if (range != undefined) {
                  mainControllerRef.current?.pause();
                }
              }}
              onUpdateFilter={updateFilter}
              setRange={setExportRange}
              setMode={setExportMode}
              setShowExportPreview={setShowExportPreview}
            />
          </div>
        </div>

        {!isDesktop && effectiveCameras.length > 1 && (
          <div className="mb-1 flex min-h-11 flex-shrink-0 items-center gap-2 px-2">
            <div
              className="flex h-8 min-w-8 flex-shrink-0 items-center justify-center gap-1 rounded-full bg-secondary px-2 text-xs font-medium text-primary"
              aria-label={t("multicam.selectedCount", {
                defaultValue: "{{count}} selected cameras",
                count: multicamCameras.length,
              })}
            >
              <FaVideo className="size-3.5 text-muted-foreground" />
              <span>{multicamCameras.length}</span>
            </div>
            <ToggleGroup
              type="multiple"
              value={multicamCameras}
              onValueChange={onMulticamSelectionChange}
              aria-label={t("multicam.selectCameras", {
                defaultValue: "Select cameras for multi-camera playback",
              })}
              className="scrollbar-container min-w-0 flex-1 justify-start overflow-x-auto py-1"
            >
              {effectiveCameras
                .filter((camera) => camera !== "birdseye")
                .map((camera) => (
                  <ToggleGroupItem
                    key={camera}
                    value={camera}
                    size="sm"
                    className="h-9 max-w-44 flex-shrink-0 truncate rounded-full border border-border/70 px-3 text-xs shadow-sm data-[state=on]:border-primary/60 data-[state=on]:bg-primary/15 data-[state=on]:text-primary"
                    aria-label={t("multicam.toggleCamera", {
                      defaultValue: "Toggle camera {{camera}}",
                      camera,
                    })}
                  >
                    <CameraNameLabel camera={camera} />
                  </ToggleGroupItem>
                ))}
            </ToggleGroup>
          </div>
        )}

        <div
          ref={mainLayoutRef}
          className={cn(
            "flex flex-1 overflow-hidden",
            isDesktop ? "flex-row" : "flex-col gap-2 landscape:flex-row",
          )}
        >
          <div
            ref={cameraLayoutRef}
            className={cn(
              "flex flex-1 flex-wrap overflow-hidden",
              isMulticam && "min-h-0 min-w-0 p-1",
              isDesktop
                ? "min-w-0 px-4"
                : isMulticam
                  ? "portrait:min-h-0 portrait:basis-[64%] portrait:flex-grow-0 landscape:flex-1"
                  : "portrait:max-h-[50dvh] portrait:flex-shrink-0 portrait:flex-grow-0 portrait:basis-auto",
            )}
          >
            <div
              className={cn(
                "flex size-full items-center",
                isMulticam && "min-h-0 min-w-0",
                mainCameraAspect == "tall"
                  ? "flex-row justify-evenly"
                  : "flex-col justify-center gap-2",
              )}
            >
              {!isMulticam && (
                <div
                  key={mainCamera}
                  className={cn(
                    "relative flex max-h-full min-h-0 min-w-0 max-w-full items-center justify-center",
                    isDesktop
                      ? // Desktop: dynamically switch between w-full and h-full based on
                        // container vs camera aspect ratio to ensure proper fitting
                        useHeightBased
                        ? "h-full"
                        : "w-full"
                      : cn(
                          "flex-shrink-0 portrait:w-full landscape:h-full",
                          mainCameraAspect == "wide"
                            ? "aspect-wide"
                            : mainCameraAspect == "tall"
                              ? "aspect-tall portrait:h-full"
                              : "aspect-video",
                        ),
                  )}
                  style={{
                    aspectRatio: getCameraAspect(mainCamera),
                  }}
                >
                {(isDesktop || isTablet) && (
                  <GenAISummaryDialog
                    review={activeReviewItem}
                    onOpen={onAnalysisOpen}
                  >
                    <GenAISummaryChip review={activeReviewItem} />
                  </GenAISummaryDialog>
                )}

                <DynamicVideoPlayer
                  className={grow}
                  camera={mainCamera}
                  timeRange={currentTimeRange}
                  cameraPreviews={allPreviews ?? []}
                  startTimestamp={playbackStart}
                  scrubTimestamp={currentTime}
                  shouldPlay={isPlaybackPlaying}
                  hotKeys={
                    exportMode != "select" && debugReplayMode != "select"
                  }
                  fullscreen={fullscreen}
                  onTimestampUpdate={handleMasterTimestampUpdate}
                  onPlaybackStateChange={handlePlaybackStateChange}
                  onPlaybackRateChange={handlePlaybackRateChange}
                  onClipEnded={onClipEnded}
                  onSeekToTime={manuallySetCurrentTime}
                  onControllerReady={(controller) => {
                    mainControllerRef.current = controller;
                    multicamControllerRefs.current[mainCamera] = controller;
                  }}
                  isScrubbing={
                    scrubbing ||
                    exportMode == "timeline" ||
                    debugReplayMode == "timeline"
                  }
                  supportsFullscreen={supportsFullScreen}
                  setFullResolution={setFullResolution}
                  toggleFullscreen={toggleFullscreen}
                  containerRef={mainLayoutRef}
                />
                </div>
              )}
              {isMulticam && (
                <div
                  className={cn(
                    "grid size-full min-h-0 min-w-0 gap-1.5",
                    multicamGridClass,
                  )}
                >
                  {multicamCameras.map((camera, index) => (
                    <div
                      key={camera}
                      className={cn(
                        "relative flex min-h-0 min-w-0 items-center justify-center overflow-hidden rounded-lg border bg-black shadow-sm transition-colors",
                        camera === mainCamera
                          ? "border-primary/60 ring-1 ring-primary/30"
                          : "border-white/10",
                        multicamCameras.length === 3 &&
                          index === 0 &&
                          (isDesktop
                            ? "row-span-2"
                            : "portrait:col-span-2"),
                      )}
                    >
                      <button
                        type="button"
                        className={cn(
                          "absolute left-1.5 top-1.5 z-40 max-w-[70%] truncate rounded-full border px-2.5 py-1 text-left text-[11px] font-medium text-white shadow-sm backdrop-blur-sm transition-colors",
                          camera === mainCamera
                            ? "border-primary/60 bg-primary/75"
                            : "border-white/15 bg-black/65",
                        )}
                        aria-pressed={camera === mainCamera}
                        aria-label={t("multicam.makePrimary", {
                          defaultValue: "Use {{camera}} as the primary camera",
                          camera,
                        })}
                        onClick={(event) => {
                          event.stopPropagation();
                          activateMulticamCamera(camera);
                        }}
                      >
                        <CameraNameLabel camera={camera} />
                      </button>
                      <DynamicVideoPlayer
                        className="size-full"
                        camera={camera}
                        timeRange={currentTimeRange}
                        cameraPreviews={allPreviews ?? []}
                        startTimestamp={playbackStart}
                        scrubTimestamp={currentTime}
                        shouldPlay={isPlaybackPlaying}
                        hotKeys={
                          camera === mainCamera &&
                          exportMode != "select" &&
                          debugReplayMode != "select"
                        }
                        fullscreen={fullscreen}
                        onTimestampUpdate={
                          camera === mainCamera
                            ? handleMasterTimestampUpdate
                            : undefined
                        }
                        onPlaybackStateChange={(playing) =>
                          handlePlaybackStateChange(playing, camera)
                        }
                        onPlaybackRateChange={handlePlaybackRateChange}
                        onClipEnded={
                          camera === mainCamera ? onClipEnded : undefined
                        }
                        onSeekToTime={manuallySetCurrentTime}
                        onControllerReady={(controller) => {
                          multicamControllerRefs.current[camera] = controller;
                          if (camera === mainCamera) {
                            mainControllerRef.current = controller;
                          }
                        }}
                        isScrubbing={
                          scrubbing ||
                          exportMode == "timeline" ||
                          debugReplayMode == "timeline"
                        }
                        supportsFullscreen={supportsFullScreen}
                        controlsActive={
                          isDesktop || activeControlsCamera === camera
                        }
                        compactControls={!isDesktop}
                        onActivateControls={() =>
                          activateMulticamCamera(camera)
                        }
                        setFullResolution={
                          camera === mainCamera
                            ? setFullResolution
                            : ignoreFullResolution
                        }
                        toggleFullscreen={toggleFullscreen}
                        containerRef={mainLayoutRef}
                      />
                    </div>
                  ))}
                </div>
              )}
              {!isMulticam && isDesktop && effectiveCameras.length > 1 && (
                <div
                  ref={previewRowRef}
                  className={cn(
                    "scrollbar-container flex flex-shrink-0 gap-2 overflow-auto",
                    mainCameraAspect == "tall"
                      ? "ml-2 h-full w-72 min-w-72 flex-col"
                      : "h-28 min-h-28 w-full",
                    previewRowOverflows ? "" : "items-center justify-center",
                    timelineType == "detail" && isDesktop && "mt-4",
                  )}
                >
                  <div className="w-2" />
                  {effectiveCameras.map((cam) => {
                    if (cam == mainCamera || cam == "birdseye") {
                      return;
                    }

                    return (
                      <Tooltip key={cam}>
                        <TooltipTrigger asChild>
                          <div
                            className={
                              mainCameraAspect == "tall" ? "w-full" : "h-full"
                            }
                            style={{
                              aspectRatio: getCameraAspect(cam),
                            }}
                          >
                            <PreviewPlayer
                              previewRef={previewRef}
                              className="size-full"
                              camera={cam}
                              timeRange={currentTimeRange}
                              cameraPreviews={allPreviews ?? []}
                              startTime={startTime}
                              isScrubbing={scrubbing}
                              isVisible={visiblePreviews.includes(cam)}
                              onControllerReady={(controller) => {
                                previewRefs.current[cam] = controller;
                                controller.scrubToTimestamp(startTime);
                              }}
                              onClick={() => onSelectCamera(cam)}
                            />
                          </div>
                        </TooltipTrigger>
                        <TooltipContent className="smart-capitalize">
                          <CameraNameLabel camera={cam} />
                        </TooltipContent>
                      </Tooltip>
                    );
                  })}
                  <div className="w-2" />
                </div>
              )}
            </div>
          </div>
          <Timeline
            contentRef={contentRef}
            mainCamera={mainCamera}
            timelineType={
              (exportRange == undefined && debugReplayRange == undefined
                ? timelineType
                : "timeline") ?? "timeline"
            }
            timeRange={timeRange}
            selectedCameras={multicamCameras}
            reviewItems={reviewItems ?? []}
            mainCameraReviewItems={mainCameraReviewItems}
            activeReviewItem={activeReviewItem}
            currentTime={currentTime}
            exportRange={
              exportMode == "timeline"
                ? exportRange
                : debugReplayMode == "timeline"
                  ? debugReplayRange
                  : undefined
            }
            setCurrentTime={setCurrentTime}
            manuallySetCurrentTime={manuallySetCurrentTime}
            setScrubbing={setScrubbing}
            setExportRange={
              debugReplayMode == "timeline"
                ? setDebugReplayRange
                : setExportRange
            }
            onAnalysisOpen={onAnalysisOpen}
            isPlaying={mainControllerRef?.current?.isPlaying() ?? false}
          />
        </div>
      </div>
    </DetailStreamProvider>
  );
}

type TimelineProps = {
  contentRef: MutableRefObject<HTMLDivElement | null>;
  timelineRef?: MutableRefObject<HTMLDivElement | null>;
  mainCamera: string;
  timelineType: TimelineType;
  timeRange: TimeRange;
  selectedCameras: string[];
  reviewItems: ReviewSegment[];
  mainCameraReviewItems: ReviewSegment[];
  activeReviewItem?: ReviewSegment;
  currentTime: number;
  exportRange?: TimeRange;
  isPlaying?: boolean;
  setCurrentTime: React.Dispatch<React.SetStateAction<number>>;
  manuallySetCurrentTime: (time: number, force: boolean) => void;
  setScrubbing: React.Dispatch<React.SetStateAction<boolean>>;
  setExportRange: (range: TimeRange) => void;
  onAnalysisOpen: (open: boolean) => void;
};
function Timeline({
  contentRef,
  timelineRef,
  mainCamera,
  timelineType,
  timeRange,
  selectedCameras,
  reviewItems,
  mainCameraReviewItems,
  activeReviewItem,
  currentTime,
  exportRange,
  isPlaying,
  setCurrentTime,
  manuallySetCurrentTime,
  setScrubbing,
  setExportRange,
  onAnalysisOpen,
}: TimelineProps) {
  const { t } = useTranslation(["views/events"]);
  const internalTimelineRef = useRef<HTMLDivElement>(null);
  const selectedTimelineRef = timelineRef || internalTimelineRef;
  const timelineCameras = selectedCameras.length
    ? selectedCameras
    : [mainCamera];
  const isMulticamTimeline = timelineCameras.length > 1;

  // timeline interaction

  const [zoomSettings, setZoomSettings] = useState({
    segmentDuration: 30,
    timestampSpread: 15,
  });

  const possibleZoomLevels: ZoomLevel[] = useMemo(
    () => [
      { segmentDuration: 30, timestampSpread: 15 },
      { segmentDuration: 15, timestampSpread: 5 },
      { segmentDuration: 5, timestampSpread: 1 },
    ],
    [],
  );

  const handleZoomChange = useCallback(
    (newZoomLevel: number) => {
      setZoomSettings(possibleZoomLevels[newZoomLevel]);
    },
    [possibleZoomLevels],
  );

  const currentZoomLevel = useMemo(
    () =>
      possibleZoomLevels.findIndex(
        (level) => level.segmentDuration === zoomSettings.segmentDuration,
      ),
    [possibleZoomLevels, zoomSettings.segmentDuration],
  );

  const { isZooming, zoomDirection } = useTimelineZoom({
    zoomSettings,
    zoomLevels: possibleZoomLevels,
    onZoomChange: handleZoomChange,
    timelineRef: selectedTimelineRef,
    timelineDuration: timeRange.after - timeRange.before,
  });

  // motion data
  const { alignStartDateToTimeline, alignEndDateToTimeline } = useTimelineUtils(
    {
      segmentDuration: zoomSettings.segmentDuration,
    },
  );

  const alignedAfter = alignStartDateToTimeline(timeRange.after);
  const alignedBefore = alignEndDateToTimeline(timeRange.before);

  const { data: motionData, isLoading } = useSWR<MotionData[]>(
    !isMulticamTimeline
      ? [
          "review/activity/motion",
          {
            before: alignedBefore,
            after: alignedAfter,
            scale: Math.round(zoomSettings.segmentDuration / 2),
            cameras: mainCamera,
          },
        ]
      : null,
  );

  const { data: noRecordings } = useSWR<RecordingSegment[]>(
    !isMulticamTimeline
      ? [
          "recordings/unavailable",
          {
            before: alignedBefore,
            after: alignedAfter,
            scale: Math.round(zoomSettings.segmentDuration),
            cameras: mainCamera,
          },
        ]
      : null,
  );

  const [exportStart, setExportStartTime] = useState<number>(0);
  const [exportEnd, setExportEndTime] = useState<number>(0);

  useEffect(() => {
    if (exportRange && exportStart != 0 && exportEnd != 0) {
      if (exportRange.after != exportStart) {
        setCurrentTime(exportStart);
      } else if (exportRange?.before != exportEnd) {
        setCurrentTime(exportEnd);
      }

      setExportRange({ after: exportStart, before: exportEnd });
    }
    // we only want to update when the export parts change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exportStart, exportEnd, setExportRange, setCurrentTime]);

  return (
    <div
      className={cn(
        "relative overflow-hidden",
        isDesktop
          ? cn(
              timelineType == "timeline"
                ? isMulticamTimeline
                  ? "w-[clamp(200px,22vw,320px)] flex-shrink-0"
                  : "w-[100px] flex-shrink-0"
                : timelineType == "detail"
                  ? "min-w-[20rem] max-w-[30%] flex-shrink-0 flex-grow-0 basis-[30rem] md:min-w-[20rem] md:max-w-[25%] lg:min-w-[30rem] lg:max-w-[33%]"
                  : "w-80 flex-shrink-0",
            )
          : cn(
              timelineType == "timeline"
                ? isMulticamTimeline
                  ? "portrait:min-h-[12rem] portrait:flex-1 landscape:min-w-[120px] landscape:w-[min(30vw,180px)] landscape:flex-shrink-0"
                  : "portrait:flex-grow landscape:w-[100px] landscape:flex-shrink-0"
                : timelineType == "detail"
                  ? "portrait:flex-grow landscape:w-[19rem] landscape:flex-shrink-0"
                  : "portrait:flex-grow landscape:w-[19rem] landscape:flex-shrink-0",
            ),
      )}
    >
      {isMobileOnly && timelineType == "timeline" && (
        <GenAISummaryDialog review={activeReviewItem} onOpen={onAnalysisOpen}>
          <GenAISummaryChip review={activeReviewItem} />
        </GenAISummaryDialog>
      )}

      {timelineType != "detail" && (
        <>
          <div className="pointer-events-none absolute inset-x-0 top-0 z-20 h-[30px] w-full bg-gradient-to-b from-secondary to-transparent"></div>
          <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 h-[30px] w-full bg-gradient-to-t from-secondary to-transparent"></div>
        </>
      )}
      {timelineType == "timeline" ? (
        isMulticamTimeline ? (
          <MultiCameraMotionTimeline
            cameras={timelineCameras}
            mainCamera={mainCamera}
            reviewItems={reviewItems}
            timelineRef={selectedTimelineRef}
            contentRef={contentRef}
            segmentDuration={zoomSettings.segmentDuration}
            timestampSpread={zoomSettings.timestampSpread}
            timelineStart={timeRange.before}
            timelineEnd={timeRange.after}
            alignedAfter={alignedAfter}
            alignedBefore={alignedBefore}
            showHandlebar={exportRange == undefined}
            showExportHandles={exportRange != undefined}
            exportStartTime={exportRange?.after}
            exportEndTime={exportRange?.before}
            setExportStartTime={setExportStartTime}
            setExportEndTime={setExportEndTime}
            handlebarTime={currentTime}
            setHandlebarTime={setCurrentTime}
            onHandlebarDraggingChange={(scrubbing) => setScrubbing(scrubbing)}
            isZooming={isZooming}
            zoomDirection={zoomDirection}
            onZoomChange={handleZoomChange}
            possibleZoomLevels={possibleZoomLevels}
            currentZoomLevel={currentZoomLevel}
          />
        ) : !isLoading ? (
          <MotionReviewTimeline
            timelineRef={selectedTimelineRef}
            segmentDuration={zoomSettings.segmentDuration}
            timestampSpread={zoomSettings.timestampSpread}
            timelineStart={timeRange.before}
            timelineEnd={timeRange.after}
            showHandlebar={exportRange == undefined}
            showExportHandles={exportRange != undefined}
            exportStartTime={exportRange?.after}
            exportEndTime={exportRange?.before}
            setExportStartTime={setExportStartTime}
            setExportEndTime={setExportEndTime}
            handlebarTime={currentTime}
            setHandlebarTime={setCurrentTime}
            events={mainCameraReviewItems}
            motion_events={motionData ?? []}
            noRecordingRanges={noRecordings ?? []}
            contentRef={contentRef}
            onHandlebarDraggingChange={(scrubbing) => setScrubbing(scrubbing)}
            isZooming={isZooming}
            zoomDirection={zoomDirection}
            onZoomChange={handleZoomChange}
            possibleZoomLevels={possibleZoomLevels}
            currentZoomLevel={currentZoomLevel}
          />
        ) : (
          <Skeleton className="size-full" />
        )
      ) : timelineType == "detail" ? (
        <DetailStream
          currentTime={currentTime}
          onSeek={(timestamp, play) =>
            manuallySetCurrentTime(timestamp, play ?? true)
          }
          reviewItems={mainCameraReviewItems}
          isPlaying={isPlaying}
        />
      ) : (
        <div className="scrollbar-container h-full overflow-auto bg-secondary">
          <div
            className={cn(
              "scrollbar-container grid h-auto grid-cols-1 gap-4 overflow-auto p-4",
              isMobile && "sm:portrait:grid-cols-2",
            )}
          >
            {mainCameraReviewItems.length === 0 ? (
              <div className="mt-5 text-center text-primary">
                {t("events.noFoundForTimePeriod")}
              </div>
            ) : (
              mainCameraReviewItems.map((review) => {
                if (review.severity === "significant_motion") {
                  return;
                }

                return (
                  <ReviewCard
                    key={review.id}
                    event={review}
                    activeReviewItem={activeReviewItem}
                    onClick={() => {
                      manuallySetCurrentTime(
                        review.start_time - REVIEW_PADDING,
                        true,
                      );
                    }}
                  />
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

type MultiCameraMotionTimelineProps = {
  cameras: string[];
  mainCamera: string;
  reviewItems: ReviewSegment[];
  timelineRef: MutableRefObject<HTMLDivElement | null>;
  contentRef: MutableRefObject<HTMLDivElement | null>;
  segmentDuration: number;
  timestampSpread: number;
  timelineStart: number;
  timelineEnd: number;
  alignedAfter: number;
  alignedBefore: number;
  showHandlebar: boolean;
  showExportHandles: boolean;
  exportStartTime?: number;
  exportEndTime?: number;
  setExportStartTime: React.Dispatch<React.SetStateAction<number>>;
  setExportEndTime: React.Dispatch<React.SetStateAction<number>>;
  handlebarTime: number;
  setHandlebarTime: React.Dispatch<React.SetStateAction<number>>;
  onHandlebarDraggingChange: (isDragging: boolean) => void;
  isZooming: boolean;
  zoomDirection: TimelineZoomDirection;
  onZoomChange: (newZoomLevel: number) => void;
  possibleZoomLevels: ZoomLevel[];
  currentZoomLevel: number;
};

function MultiCameraMotionTimeline({
  cameras,
  mainCamera,
  reviewItems,
  timelineRef,
  contentRef,
  segmentDuration,
  timestampSpread,
  timelineStart,
  timelineEnd,
  alignedAfter,
  alignedBefore,
  showHandlebar,
  showExportHandles,
  exportStartTime,
  exportEndTime,
  setExportStartTime,
  setExportEndTime,
  handlebarTime,
  setHandlebarTime,
  onHandlebarDraggingChange,
  isZooming,
  zoomDirection,
  onZoomChange,
  possibleZoomLevels,
  currentZoomLevel,
}: MultiCameraMotionTimelineProps) {
  const timelineDuration = useMemo(
    () => timelineStart - timelineEnd + 4 * segmentDuration,
    [segmentDuration, timelineEnd, timelineStart],
  );
  const { alignStartDateToTimeline } = useTimelineUtils({
    segmentDuration,
    timelineDuration,
    timelineRef,
  });
  const timelineStartAligned = useMemo(
    () => alignStartDateToTimeline(timelineStart) + 2 * segmentDuration,
    [alignStartDateToTimeline, segmentDuration, timelineStart],
  );
  const segments = useMemo(() => {
    const segmentTimes: number[] = [];
    let segmentTime = timelineStartAligned;

    for (let i = 0; i < Math.ceil(timelineDuration / segmentDuration); i++) {
      segmentTimes.push(segmentTime);
      segmentTime -= segmentDuration;
    }

    return segmentTimes;
  }, [segmentDuration, timelineDuration, timelineStartAligned]);

  const primarySegmentsRef = useRef<VirtualizedMotionSegmentsRef>(null);
  const scrollToSegment = useCallback(
    (segmentTime: number, ifNeeded?: boolean) =>
      primarySegmentsRef.current?.scrollToSegment(segmentTime, ifNeeded),
    [],
  );
  const dense = !isDesktop && cameras.length > 2;
  const laneGridStyle = useMemo(
    () => ({
      gridTemplateColumns: `repeat(${cameras.length}, minmax(0, 1fr))`,
    }),
    [cameras.length],
  );

  return (
    <div
      className={cn(
        "relative size-full min-h-0 min-w-0 overflow-hidden bg-border",
        !isDesktop &&
          "portrait:rounded-t-xl portrait:border-t landscape:rounded-l-xl landscape:border-l",
      )}
    >
      <ReviewTimeline
        timelineRef={timelineRef}
        contentRef={contentRef}
        segmentDuration={segmentDuration}
        timelineDuration={timelineDuration}
        timelineStartAligned={timelineStartAligned}
        showHandlebar={showHandlebar}
        showExportHandles={showExportHandles}
        handlebarTime={handlebarTime}
        setHandlebarTime={setHandlebarTime}
        onHandlebarDraggingChange={onHandlebarDraggingChange}
        exportStartTime={exportStartTime}
        exportEndTime={exportEndTime}
        setExportStartTime={setExportStartTime}
        setExportEndTime={setExportEndTime}
        dense={dense}
        segments={segments}
        scrollToSegment={scrollToSegment}
        isZooming={isZooming}
        zoomDirection={zoomDirection}
        onZoomChange={onZoomChange}
        possibleZoomLevels={possibleZoomLevels}
        currentZoomLevel={currentZoomLevel}
      >
        <div
          className="grid min-w-0 gap-px bg-border"
          style={{
            ...laneGridStyle,
            height: `${segments.length * 8}px`,
          }}
        >
          {cameras.map((camera, index) => (
            <MultiCameraMotionTimelineLane
              key={camera}
              camera={camera}
              index={index}
              reviewItems={reviewItems}
              timelineRef={timelineRef}
              contentRef={contentRef}
              segments={segments}
              segmentDuration={segmentDuration}
              timestampSpread={timestampSpread}
              alignedAfter={alignedAfter}
              alignedBefore={alignedBefore}
              setHandlebarTime={setHandlebarTime}
              dense={dense}
              virtualizedRef={index === 0 ? primarySegmentsRef : undefined}
            />
          ))}
        </div>
      </ReviewTimeline>

      <div
        className="pointer-events-none absolute inset-x-0 top-1 z-30 grid min-w-0 gap-px px-1"
        style={laneGridStyle}
      >
        {cameras.map((camera) => (
          <div
            key={camera}
            className={cn(
              "mx-0.5 flex min-w-0 items-center gap-1 truncate rounded-full border px-1.5 py-0.5 text-[9px] font-medium leading-3 shadow-sm backdrop-blur-sm md:text-[10px]",
              camera === mainCamera
                ? "border-primary/50 bg-primary/75 text-primary-foreground"
                : "border-border/70 bg-secondary/85 text-primary",
            )}
          >
            <span
              className={cn(
                "size-1.5 flex-shrink-0 rounded-full",
                camera === mainCamera
                  ? "bg-white"
                  : "bg-muted-foreground/60",
              )}
            />
            <span className="truncate">
              <CameraNameLabel camera={camera} />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

type MultiCameraMotionTimelineLaneProps = {
  camera: string;
  index: number;
  reviewItems: ReviewSegment[];
  timelineRef: MutableRefObject<HTMLDivElement | null>;
  contentRef: MutableRefObject<HTMLDivElement | null>;
  segments: number[];
  segmentDuration: number;
  timestampSpread: number;
  alignedAfter: number;
  alignedBefore: number;
  setHandlebarTime: React.Dispatch<React.SetStateAction<number>>;
  dense: boolean;
  virtualizedRef?: React.Ref<VirtualizedMotionSegmentsRef>;
};

function MultiCameraMotionTimelineLane({
  camera,
  index,
  reviewItems,
  timelineRef,
  contentRef,
  segments,
  segmentDuration,
  timestampSpread,
  alignedAfter,
  alignedBefore,
  setHandlebarTime,
  dense,
  virtualizedRef,
}: MultiCameraMotionTimelineLaneProps) {
  const { data: motionData, isLoading } = useSWR<MotionData[]>([
    "review/activity/motion",
    {
      before: alignedBefore,
      after: alignedAfter,
      scale: Math.round(segmentDuration / 2),
      cameras: camera,
    },
  ]);

  const { data: noRecordings } = useSWR<RecordingSegment[]>([
    "recordings/unavailable",
    {
      before: alignedBefore,
      after: alignedAfter,
      scale: Math.round(segmentDuration),
      cameras: camera,
    },
  ]);

  const cameraReviewItems = useMemo(
    () => reviewItems.filter((review) => review.camera === camera),
    [camera, reviewItems],
  );
  const { getMotionSegmentValue } = useMotionSegmentUtils(
    segmentDuration,
    motionData ?? [],
  );
  const getRecordingAvailability = useCallback(
    (time: number): boolean | undefined => {
      if (noRecordings == undefined) {
        return undefined;
      }

      return !noRecordings.some(
        (range) => time >= range.start_time && time < range.end_time,
      );
    },
    [noRecordings],
  );

  return (
    <div className="relative min-h-0 min-w-0 bg-secondary">
      <VirtualizedMotionSegments
        ref={virtualizedRef}
        timelineRef={timelineRef}
        segments={segments}
        events={cameraReviewItems}
        motion_events={motionData ?? []}
        segmentDuration={segmentDuration}
        timestampSpread={timestampSpread}
        showMinimap={false}
        contentRef={contentRef}
        setHandlebarTime={setHandlebarTime}
        dense={dense}
        motionOnly={false}
        getMotionSegmentValue={getMotionSegmentValue}
        getRecordingAvailability={getRecordingAvailability}
        alwaysShowMotionLine={false}
        showTimestamps={index === 0}
      />
      {isLoading && (
        <div className="pointer-events-none absolute inset-0 z-20 bg-secondary/50">
          <Skeleton className="size-full rounded-none" />
        </div>
      )}
    </div>
  );
}
