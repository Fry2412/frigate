import {
  MutableRefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import useSWR from "swr";
import { FrigateConfig } from "@/types/frigateConfig";
import { Preview } from "@/types/preview";
import { PreviewPlayback } from "@/types/playback";
import { baseUrl } from "@/api/baseUrl";
import { isAndroid, isChrome, isMobile } from "react-device-detect";
import { TimeRange } from "@/types/timeline";
import { Skeleton } from "../ui/skeleton";
import { cn } from "@/lib/utils";
import {
  getPreviewForTimeRange,
  usePreviewForTimeRange,
} from "@/hooks/use-camera-previews";
import { useTranslation } from "react-i18next";
import { useCameraFriendlyName } from "@/hooks/use-camera-friendly-name";

type PreviewPlayerProps = {
  previewRef?: (ref: HTMLDivElement | null) => void;
  className?: string;
  camera: string;
  timeRange: TimeRange;
  cameraPreviews: Preview[];
  startTime?: number;
  isScrubbing: boolean;
  forceAspect?: number;
  isVisible?: boolean;
  onControllerReady: (controller: PreviewController) => void;
  onClick?: () => void;
};
export default function PreviewPlayer({
  previewRef,
  className,
  camera,
  timeRange,
  cameraPreviews,
  startTime,
  isScrubbing,
  isVisible = true,
  onControllerReady,
  onClick,
}: PreviewPlayerProps) {
  const [currentHourFrame, setCurrentHourFrame] = useState<string>();
  const currentPreview = usePreviewForTimeRange(
    cameraPreviews,
    camera,
    timeRange,
  );

  if (currentPreview) {
    return (
      <PreviewVideoPlayer
        visibilityRef={previewRef}
        className={className}
        camera={camera}
        timeRange={timeRange}
        cameraPreviews={cameraPreviews}
        initialPreview={currentPreview}
        startTime={startTime}
        isScrubbing={isScrubbing}
        isVisible={isVisible}
        currentHourFrame={currentHourFrame}
        onControllerReady={onControllerReady}
        onClick={onClick}
        setCurrentHourFrame={setCurrentHourFrame}
      />
    );
  }

  // The frame cache is also a recovery path while an hourly MP4 is still
  // being converted or when its database entry is temporarily unavailable.
  // Restricting this fallback to the current hour made every other gap appear
  // as a black tile in the multicam view.
  return (
    <PreviewFramesPlayer
      className={className}
      camera={camera}
      timeRange={timeRange}
      startTime={startTime}
      onControllerReady={onControllerReady}
      onClick={onClick}
      setCurrentHourFrame={setCurrentHourFrame}
    />
  );
}

export abstract class PreviewController {
  public camera = "";

  constructor(camera: string) {
    this.camera = camera;
  }

  abstract scrubToTimestamp(time: number): boolean;

  abstract finishedSeeking(): void;

  abstract setNewPreviewStartTime(time: number): void;
}

type PreviewVideoPlayerProps = {
  visibilityRef?: (ref: HTMLDivElement | null) => void;
  className?: string;
  camera: string;
  timeRange: TimeRange;
  cameraPreviews: Preview[];
  initialPreview?: Preview;
  startTime?: number;
  isScrubbing: boolean;
  isVisible: boolean;
  currentHourFrame?: string;
  onControllerReady: (controller: PreviewVideoController) => void;
  onClick?: () => void;
  setCurrentHourFrame: (src: string | undefined) => void;
};
function PreviewVideoPlayer({
  visibilityRef,
  className,
  camera,
  timeRange,
  cameraPreviews,
  initialPreview,
  startTime,
  isScrubbing,
  isVisible,
  currentHourFrame,
  onControllerReady,
  onClick,
  setCurrentHourFrame,
}: PreviewVideoPlayerProps) {
  const { t } = useTranslation(["components/player"]);
  const { data: config } = useSWR<FrigateConfig>("config");

  const cameraName = useCameraFriendlyName(camera);
  // controlling playback

  const previewRef = useRef<HTMLVideoElement | null>(null);
  const [previewElement, setPreviewElement] = useState<HTMLVideoElement | null>(
    null,
  );
  const setPreviewRef = useCallback((element: HTMLVideoElement | null) => {
    previewRef.current = element;
    setPreviewElement(element);
  }, []);
  const controller = useMemo(() => {
    if (!config || !previewElement) {
      return undefined;
    }

    return new PreviewVideoController(camera, previewRef);
  }, [camera, config, previewElement]);

  useEffect(() => {
    if (!controller) {
      return;
    }

    if (controller) {
      onControllerReady(controller);
    }
    // we only want to fire once when players are ready
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller]);

  useEffect(() => {
    if (!controller) {
      return;
    }

    controller.scrubbing = isScrubbing;
  }, [controller, isScrubbing]);

  // initial state

  const [firstLoad, setFirstLoad] = useState(true);

  useEffect(() => {
    if (cameraPreviews && cameraPreviews.length > 0) {
      setFirstLoad(false);
    }
  }, [cameraPreviews]);

  const [currentPreview, setCurrentPreview] = useState(initialPreview);

  const onPreviewSeeked = useCallback(() => {
    if (!controller) {
      return;
    }

    setCurrentHourFrame(undefined);

    if (isAndroid && isChrome) {
      // android/chrome glitches when setting currentTime at the same time as onSeeked
      setTimeout(() => controller.finishedSeeking(), 25);
    } else {
      controller.finishedSeeking();
    }
    // we only want to update on controller change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller]);

  // canvas to cover preview transition

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [videoSize, setVideoSize] = useState<number[]>([0, 0]);
  const [changeoverTimeout, setChangeoverTimeout] = useState<NodeJS.Timeout>();

  const changeSource = useCallback(
    (newPreview: Preview | undefined, video: HTMLVideoElement | null) => {
      if (!newPreview || !video) {
        setCurrentPreview(newPreview);
        return;
      }

      if (!canvasRef.current && videoSize[0] > 0) {
        const canvas = document.createElement("canvas");
        canvas.width = videoSize[0];
        canvas.height = videoSize[1];
        canvasRef.current = canvas;
      }

      const context = canvasRef.current?.getContext("2d");

      if (context) {
        context.drawImage(video, 0, 0, videoSize[0], videoSize[1]);
        setCurrentHourFrame(canvasRef.current?.toDataURL("image/webp"));
      }

      setCurrentPreview(newPreview);
      const timeout = setTimeout(() => {
        if (timeout) {
          clearTimeout(timeout);
          setChangeoverTimeout(undefined);
        }

        previewRef.current?.load();
      }, 1000);
      setChangeoverTimeout(timeout);

      // we only want this to change when current preview changes
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [setCurrentHourFrame, videoSize],
  );

  useEffect(() => {
    if (!controller) {
      return;
    }

    const preview = getPreviewForTimeRange(cameraPreviews, camera, timeRange);

    if (preview != currentPreview) {
      controller.newPreviewLoaded = false;
      changeSource(preview, previewRef.current);
    }

    controller.newPlayback({
      preview,
      timeRange,
    });

    // we only want this to change when recordings update
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller, timeRange, changeSource]);

  return (
    <div
      ref={visibilityRef}
      className={cn(
        "relative flex w-full justify-center overflow-hidden rounded-lg bg-black md:rounded-2xl",
        onClick && "cursor-pointer",
        className,
      )}
      data-camera={camera}
      onClick={onClick}
    >
      <img
        className={`absolute size-full object-contain ${currentHourFrame ? "visible" : "invisible"}`}
        src={currentHourFrame}
        onLoad={() => {
          if (changeoverTimeout) {
            clearTimeout(changeoverTimeout);
            setChangeoverTimeout(undefined);
          }

          previewRef.current?.load();
        }}
      />
      {isVisible && (
        <video
          ref={setPreviewRef}
          className={`absolute size-full ${currentHourFrame ? "invisible" : "visible"}`}
          preload="auto"
          autoPlay
          playsInline
          muted
          disableRemotePlayback
          disablePictureInPicture
          onSeeked={onPreviewSeeked}
          onLoadedData={() => {
            if (firstLoad) {
              setFirstLoad(false);
            }

            if (
              previewRef.current &&
              startTime != undefined &&
              currentPreview
            ) {
              previewRef.current.currentTime =
                startTime - currentPreview.start;
            }

            if (controller) {
              controller.previewReady();
            } else {
              previewRef.current?.pause();
            }

            if (previewRef.current) {
              setVideoSize([
                previewRef.current.videoWidth,
                previewRef.current.videoHeight,
              ]);
            }
          }}
        >
          {currentPreview != undefined && (
            <source
              src={`${baseUrl}${currentPreview.src.substring(1)}`}
              type={currentPreview.type}
            />
          )}
        </video>
      )}
      {cameraPreviews && !currentPreview && (
        <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-background_alt text-primary dark:bg-black md:rounded-2xl">
          {t("noPreviewFoundFor", { camera: cameraName })}
        </div>
      )}
      {firstLoad && <Skeleton className="absolute aspect-video size-full" />}
    </div>
  );
}

class PreviewVideoController extends PreviewController {
  // main state
  private previewRef: MutableRefObject<HTMLVideoElement | null>;
  private timeRange: TimeRange | undefined = undefined;

  // preview
  private preview: Preview | undefined = undefined;
  private timeToSeek: number | undefined = undefined;
  public scrubbing = false;
  public newPreviewLoaded = true;
  private seeking = false;

  constructor(
    camera: string,
    previewRef: MutableRefObject<HTMLVideoElement | null>,
  ) {
    super(camera);
    this.previewRef = previewRef;
  }

  newPlayback(newPlayback: PreviewPlayback) {
    this.preview = newPlayback.preview;
    this.seeking = false;

    this.timeRange = newPlayback.timeRange;
  }

  override scrubToTimestamp(time: number): boolean {
    if (
      !this.newPreviewLoaded ||
      !this.previewRef.current ||
      !this.preview ||
      !this.timeRange
    ) {
      return false;
    }

    if (time < this.preview.start || time > this.preview.end) {
      return false;
    }

    const seekTime = Math.max(0, time - this.preview.start);

    if (this.seeking) {
      this.timeToSeek = time;
    } else {
      this.previewRef.current.currentTime = seekTime;
      this.seeking = true;
    }

    return true;
  }

  override finishedSeeking() {
    if (!this.previewRef.current || !this.preview) {
      return;
    }

    if (this.timeToSeek !== undefined) {
      if (
        this.timeToSeek < this.preview.start ||
        this.timeToSeek > this.preview.end
      ) {
        this.timeToSeek = undefined;
        this.seeking = false;
        return;
      }

      const diff = Math.round(
        this.timeToSeek -
          this.preview.start -
          this.previewRef.current.currentTime,
      );

      const scrubLimit = isMobile ? 1 : 0.5;

      if (Math.abs(diff) >= scrubLimit) {
        // only seek if there is an appropriate amount of time difference
        this.previewRef.current.currentTime =
          this.timeToSeek - this.preview.start;
      } else {
        this.seeking = false;
        this.timeToSeek = undefined;
      }
    } else {
      this.seeking = false;
    }
  }

  override setNewPreviewStartTime(time: number) {
    this.timeToSeek = time;
  }

  previewReady() {
    this.newPreviewLoaded = true;
    this.seeking = false;
    this.previewRef.current?.pause();

    if (this.timeToSeek !== undefined) {
      this.finishedSeeking();
    }
  }
}

type PreviewFramesPlayerProps = {
  className?: string;
  camera: string;
  timeRange: TimeRange;
  startTime?: number;
  onControllerReady: (controller: PreviewController) => void;
  onClick?: () => void;
  setCurrentHourFrame: (src: string | undefined) => void;
};
function PreviewFramesPlayer({
  className,
  camera,
  timeRange,
  startTime,
  setCurrentHourFrame,
  onControllerReady,
  onClick,
}: PreviewFramesPlayerProps) {
  const { t } = useTranslation(["components/player"]);

  const cameraName = useCameraFriendlyName(camera);
  // frames data

  const { data: previewFrames } = useSWR<string[]>(
    `preview/${camera}/start/${Math.floor(timeRange.after)}/end/${Math.ceil(
      timeRange.before,
    )}/frames`,
    { revalidateOnFocus: false },
  );
  const frameTimes = useMemo(() => {
    if (!previewFrames) {
      return undefined;
    }

    return previewFrames.map((frame) =>
      // @ts-expect-error we know this item will exist
      parseFloat(frame.split("-").at(-1).slice(undefined, -5)),
    );
  }, [previewFrames]);

  // controlling frames

  const imgRef = useRef<HTMLImageElement | null>(null);
  const [previewElement, setPreviewElement] =
    useState<HTMLImageElement | null>(null);
  const setPreviewRef = useCallback((element: HTMLImageElement | null) => {
    imgRef.current = element;
    setPreviewElement(element);
  }, []);
  const controller = useMemo(() => {
    if (!frameTimes || !previewElement) {
      return undefined;
    }

    return new PreviewFramesController(
      camera,
      imgRef,
      frameTimes,
      setCurrentHourFrame,
    );
  }, [camera, frameTimes, previewElement, setCurrentHourFrame]);

  // initial state

  const [firstLoad, setFirstLoad] = useState(true);

  useEffect(() => {
    if (previewFrames != undefined && previewFrames.length == 0) {
      setFirstLoad(false);
    }
  }, [previewFrames]);

  useEffect(() => {
    if (!controller) {
      return;
    }

    if (controller) {
      onControllerReady(controller);
    }

    // we only want to fire once when players are ready
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller]);

  const onImageLoaded = useCallback(() => {
    setFirstLoad(false);

    if (!controller) {
      return;
    }

    controller.finishedSeeking();
  }, [controller]);

  useEffect(() => {
    if (!controller) {
      return;
    }

    if (!startTime) {
      controller.scrubToTimestamp(frameTimes?.at(-1) ?? timeRange.after);
    } else {
      controller.scrubToTimestamp(startTime);
    }
    // we only want to calculate this once
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller]);

  return (
    <div
      className={cn(
        "relative flex w-full justify-center",
        className,
        onClick && "cursor-pointer",
      )}
      onClick={onClick}
    >
      <img
        ref={setPreviewRef}
        className={`size-full rounded-lg bg-black object-contain md:rounded-2xl`}
        loading="eager"
        onLoad={onImageLoaded}
        onError={() => {
          setFirstLoad(false);
          controller?.frameLoadFailed();
        }}
      />
      {previewFrames?.length === 0 && (
        <div className="-y-translate-1/2 align-center absolute inset-x-0 top-1/2 rounded-lg bg-background_alt text-center text-primary dark:bg-black md:rounded-2xl">
          {t("noPreviewFoundFor", { cameraName: cameraName })}
        </div>
      )}
      {firstLoad && <Skeleton className="absolute aspect-video size-full" />}
    </div>
  );
}

class PreviewFramesController extends PreviewController {
  imgController: MutableRefObject<HTMLImageElement | null>;
  frameTimes: number[];
  seeking: boolean = false;
  private timeToSeek: number | undefined = undefined;
  private setCurrentFrame: (src: string | undefined) => void;

  constructor(
    camera: string,
    imgController: MutableRefObject<HTMLImageElement | null>,
    frameTimes: number[],
    setCurrentFrame: (src: string | undefined) => void,
  ) {
    super(camera);
    this.imgController = imgController;
    this.frameTimes = frameTimes;
    this.setCurrentFrame = setCurrentFrame;
  }

  private getFrameForTimestamp(time: number): number | undefined {
    return (
      this.frameTimes.find((frameTime) => time <= frameTime) ??
      this.frameTimes.at(-1)
    );
  }

  override scrubToTimestamp(time: number): boolean {
    if (!this.imgController.current) {
      return false;
    }

    // Use the first frame at or after the requested timestamp. If the
    // recorder has not written a frame after the timestamp yet (common near
    // the live edge), keep the last available frame instead of leaving the
    // preview black.
    const frame = this.getFrameForTimestamp(time);

    if (frame === undefined) return false;

    if (this.seeking) {
      this.timeToSeek = frame;
    } else {
      const newSrc = `${baseUrl}api/preview/preview_${this.camera}-${frame}.webp/thumbnail.webp`;

      if (this.imgController.current.src != newSrc) {
        this.imgController.current.src = newSrc;
        this.seeking = true;
      } else if (!this.imgController.current.complete) {
        this.seeking = true;
      }
    }

    return true;
  }

  override finishedSeeking() {
    if (!this.imgController.current) {
      return false;
    }

    if (this.timeToSeek !== undefined) {
      const timeToSeek = this.timeToSeek;
      this.timeToSeek = undefined;
      const newSrc = `${baseUrl}api/preview/preview_${this.camera}-${timeToSeek}.webp/thumbnail.webp`;

      if (this.imgController.current.src != newSrc) {
        this.imgController.current.src = newSrc;
        this.setCurrentFrame(newSrc);
        this.seeking = true;
      } else {
        this.seeking = false;
      }
    } else {
      this.seeking = false;
    }
  }

  override setNewPreviewStartTime(time: number) {
    this.timeToSeek = this.getFrameForTimestamp(time);
  }

  frameLoadFailed() {
    // A frame can disappear while the preview converter moves or cleans the
    // cache. Allow the next scrub request to select another frame instead of
    // keeping the controller permanently in a seeking state.
    this.seeking = false;
    this.timeToSeek = undefined;
  }
}
