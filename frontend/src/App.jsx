import { useEffect, useRef, useState } from "react";
import "./App.css";
import {
	createJob,
	createJobPollSnapshot,
	deriveProcessingSteps,
	formatJobStatusMessage,
	getAnnotatedFrameUrl,
	getDownloadUrl,
	getJobPollDelayMs,
	getJobSegments,
	getJobSegmentsEnriched,
	getJobStatus,
	getProcessingProgress,
	INITIAL_PROCESSING_STEPS,
	nextJobPollDelayIndex,
	sendVoiceCommand,
} from "./api/equalview";
import {
	PlusIcon,
	AudioIcon,
	SceneIcon,
	NarrationIcon,
	OutputIcon,
	MicIcon,
	CheckIcon,
	DownloadIcon
} from "./icons/Icons";

function formatSeconds(value) {
	return typeof value === "number" ? `${value.toFixed(1)}s` : "-";
}

function ProcessingStep({ icon, title, state }) {
	return (
		<div className={`processing-step ${state}`}>
			<div className="step-icon-circle">
				{state === "completed" ? <CheckIcon /> : icon}
			</div>

			<p className="step-title">{title}</p>

			<p className="step-state">
				{state === "in-progress" && "In progress"}
				{state === "waiting" && "Waiting"}
				{state === "completed" && "Completed"}
				{state === "failed" && "Failed"}
			</p>
		</div>
	);
}

const PROCESSING_STEP_ICONS = [
	<AudioIcon />,
	<SceneIcon />,
	<NarrationIcon />,
	<OutputIcon />,
];

function FramePreviewCard({ jobId, frame }) {
	const imageUrl = getAnnotatedFrameUrl(jobId, frame);
	const personLabel = frame.personIds?.length
		? frame.personIds.join(", ")
		: "No faces";

	return (
		<article className="frame-preview-card">
			<div className="frame-preview-image-wrap">
				{imageUrl ? (
					<img
						className="frame-preview-image"
						src={imageUrl}
						alt={`Annotated frame at ${frame.timestamp}s`}
						loading="lazy"
					/>
				) : (
					<div className="frame-preview-placeholder">No image</div>
				)}
			</div>
			<div className="frame-preview-meta">
				<p className="frame-preview-time">{frame.timestamp.toFixed(2)}s</p>
				<p className="frame-preview-segment">{frame.segmentId}</p>
				<p className="frame-preview-persons">{personLabel}</p>
			</div>
		</article>
	);
}

function App() {
	const [phase, setPhase] = useState("upload");
	const [videoFile, setVideoFile] = useState(null);
	const [thumbnailURL, setThumbnailURL] = useState("");
	const [jobId, setJobId] = useState(null);
	const [segments, setSegments] = useState([]);
	const [enrichedResult, setEnrichedResult] = useState(null);
	const [jobProgress, setJobProgress] = useState(0);
	const [isListening, setIsListening] = useState(false);
	const [status, setStatus] = useState("");
	const [stepTimings, setStepTimings] = useState(null);

	const videoRef = useRef(null);
	const mediaRecorderRef = useRef(null);
	const audioStreamRef = useRef(null);
	const audioChunksRef = useRef([]);

	const [processingSteps, setProcessingSteps] = useState(INITIAL_PROCESSING_STEPS);

	async function handleVideoUpload(event) {
		const file = event.target.files[0];

		if (!file) return;

		setVideoFile(file);
		setJobId(null);
		setSegments([]);
		setEnrichedResult(null);
		setJobProgress(0);
		setProcessingSteps(INITIAL_PROCESSING_STEPS);
		setStepTimings(null);
		setPhase("processing");
		setStatus("Uploading video...");

		try {
			const thumbnail = await createVideoThumbnail(file);
			setThumbnailURL(thumbnail);

			const { job_id } = await createJob(file);
			setJobId(job_id);
			setStatus("Waiting for worker...");
		} catch (error) {
			console.error(error);
			setStatus("Failed to start video processing.");
			setPhase("upload");
		}
	}

	function createVideoThumbnail(file) {
		return new Promise((resolve, reject) => {
			const video = document.createElement("video");
			const canvas = document.createElement("canvas");
			const url = URL.createObjectURL(file);

			video.preload = "metadata";
			video.muted = true;
			video.playsInline = true;
			video.src = url;

			video.onloadedmetadata = () => {
				video.currentTime = Math.min(0.15, video.duration || 0);
			};

			video.onseeked = () => {
				canvas.width = video.videoWidth;
				canvas.height = video.videoHeight;

				const context = canvas.getContext("2d");
				context.drawImage(video, 0, 0, canvas.width, canvas.height);

				const imageURL = canvas.toDataURL("image/jpeg", 0.9);

				URL.revokeObjectURL(url);
				resolve(imageURL);
			};

			video.onerror = () => {
				URL.revokeObjectURL(url);
				reject(new Error("Could not create video thumbnail."));
			};
		});
	}

	function speak(text) {
		if (!window.speechSynthesis) return;

		window.speechSynthesis.cancel();

		const utterance = new SpeechSynthesisUtterance(text);
		utterance.lang = "en-US";
		utterance.rate = 1;
		utterance.pitch = 1;

		window.speechSynthesis.speak(utterance);
	}

	async function startListening() {
		if (!videoFile) {
			setStatus("Please upload a video first.");
			return;
		}

		try {
			const stream = await navigator.mediaDevices.getUserMedia({
				audio: true
			});

			audioStreamRef.current = stream;
			audioChunksRef.current = [];

			const mediaRecorder = new MediaRecorder(stream);
			mediaRecorderRef.current = mediaRecorder;

			mediaRecorder.onstart = () => {
				setIsListening(true);
				setStatus("Recording voice...");
				speak("I'm listening.");
			};

			mediaRecorder.ondataavailable = (event) => {
				if (event.data.size > 0) {
					audioChunksRef.current.push(event.data);
				}
			};

			mediaRecorder.onstop = async () => {
				setStatus("Voice recorded. Processing...");
				speak("Voice recorded. Processing your command.");

				const audioBlob = new Blob(audioChunksRef.current, {
					type: "audio/webm"
				});

				audioChunksRef.current = [];

				await handleVoiceUpload(audioBlob);

				if (audioStreamRef.current) {
					audioStreamRef.current.getTracks().forEach((track) => {
						track.stop();
					});

					audioStreamRef.current = null;
				}

				mediaRecorderRef.current = null;
				setIsListening(false);
			};

			mediaRecorder.start();
		} catch (error) {
			setIsListening(false);

			if (error.name === "NotAllowedError") {
				setStatus("Microphone permission is blocked.");
				return;
			}

			setStatus("Could not access microphone.");
		}
	}

	function stopListening() {
		if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
			mediaRecorderRef.current.stop();
			return;
		}

		if (audioStreamRef.current) {
			audioStreamRef.current.getTracks().forEach((track) => {
				track.stop();
			});

			audioStreamRef.current = null;
		}

		setIsListening(false);
		setStatus("");
	}

	function toggleListening() {
		if (isListening) {
			stopListening();
		} else {
			startListening();
		}
	}

	function handleUserCommand(command) {
		if (!command) {
			setStatus("No command detected.");
			return;
		}

		const lowerCommand = command.toLowerCase();

		if (lowerCommand.includes("explain")) {
			if (videoRef.current) {
				videoRef.current.pause();
			}

			setStatus("Explain command detected.");
			return;
		}

		setStatus(`Heard: ${command}`);
	}

	async function handleVoiceUpload(audioBlob) {
		try {
			setStatus("Sending voice to backend...");

			const data = await sendVoiceCommand(audioBlob);

			console.log("Backend response:", data);

			if (data.text) {
				handleUserCommand(data.text);
				return;
			}

			setStatus(`Backend received audio: ${data.filename}`);
		} catch (error) {
			console.error(error);
			setStatus("Failed to send voice to backend.");
		}
	}

	function downloadSegments() {
		if (!segments.length) {
			setStatus("No segments available to download.");
			return;
		}

		const blob = new Blob([JSON.stringify({ segments }, null, 2)], {
			type: "application/json",
		});
		const url = URL.createObjectURL(blob);
		const anchor = document.createElement("a");
		anchor.href = url;
		anchor.download = `segments-${jobId || "result"}.json`;
		anchor.click();
		URL.revokeObjectURL(url);
		setStatus("Segments downloaded.");
	}

	function goHome() {
		stopListening();

		setPhase("upload");
		setVideoFile(null);
		setThumbnailURL("");
		setJobId(null);
		setSegments([]);
		setEnrichedResult(null);
		setJobProgress(0);
		setStatus("");
		setProcessingSteps(INITIAL_PROCESSING_STEPS);
		setStepTimings(null);
	}

	useEffect(() => {
		if (phase !== "processing" || !jobId) return;

		let cancelled = false;
		let timeoutId = null;
		let delayIndex = 0;
		let previousSnapshot = null;

		function scheduleNextPoll() {
			timeoutId = setTimeout(pollJob, getJobPollDelayMs(delayIndex));
		}

		async function pollJob() {
			try {
				const job = await getJobStatus(jobId);
				if (cancelled) return;

				const snapshot = createJobPollSnapshot(job);
				delayIndex = nextJobPollDelayIndex(delayIndex, previousSnapshot, snapshot);
				previousSnapshot = snapshot;

				const nextProcessingSteps = deriveProcessingSteps(job);
				setProcessingSteps(nextProcessingSteps);
				setJobProgress(getProcessingProgress(nextProcessingSteps));
				setStatus(formatJobStatusMessage(job));

				if (
					job.status === "COMPLETED" &&
					job.face_status === "COMPLETED" &&
					job.narration_status === "COMPLETED" &&
					job.combine_status === "COMPLETED"
				) {
					const [segData, enrichedData] = await Promise.allSettled([
						getJobSegments(jobId),
						getJobSegmentsEnriched(jobId),
					]);
					if (cancelled) return;

					if (segData.status === "fulfilled") {
						setSegments(segData.value.segments ?? []);
					}
					if (enrichedData.status === "fulfilled") {
						setEnrichedResult(enrichedData.value);
					}

					setStepTimings({
						dialogue: job.dialogue_seconds,
						face: job.face_seconds,
						narration: job.narration_seconds,
						combine: job.combine_seconds,
					});
					setPhase("watching");
					setStatus("");
					return;
				}

				if (
					job.status === "FAILED" ||
					job.face_status === "FAILED" ||
					job.narration_status === "FAILED" ||
					job.combine_status === "FAILED"
				) {
					setStatus(
						job.error ||
							job.face_error ||
							job.narration_error ||
							job.combine_error ||
							"Processing failed."
					);
					return;
				}

				scheduleNextPoll();
			} catch (error) {
				console.error(error);
				if (!cancelled) {
					setStatus(error.message || "Failed to check job status.");
					scheduleNextPoll();
				}
			}
		}

		pollJob();

		return () => {
			cancelled = true;
			if (timeoutId) clearTimeout(timeoutId);
		};
	}, [phase, jobId]);

	useEffect(() => {
		function handleKeyDown(event) {
			if (event.repeat) return;
			if (phase !== "watching") return;

			if (event.key.toLowerCase() === "q") {
				event.preventDefault();
				toggleListening();
			}
		}

		window.addEventListener("keydown", handleKeyDown);

		return () => {
			window.removeEventListener("keydown", handleKeyDown);
		};
	}, [isListening, videoFile, phase]);

	const speechCount = segments.filter((segment) => segment.speech === true).length;
	const silenceCount = segments.filter((segment) => segment.speech === false).length;

	const previewFrames = enrichedResult
		? (() => {
				const previews = [];
				for (const seg of enrichedResult?.segments ?? []) {
					for (const frame of seg.frames ?? []) {
						if (!frame?.annotated_path && !frame?.path) continue;
						previews.push({
							...frame,
							segmentId: seg.segment_id,
							personIds: (frame.faces ?? []).map((f) => f.person_id).filter(Boolean),
						});
					}
				}
				return previews.sort((a, b) => a.timestamp - b.timestamp);
			})()
		: [];

	return (
		<div className="app">
			<header className="app-header">
				<button className="brand-button" onClick={goHome}>
					EqualView
				</button>
			</header>

			{phase === "upload" && (
				<main className="stage-page">
					<h1 className="stage-title">Hear your movie </h1>

					<div className="screen-shell">
						<label className="upload-video-box">
							<input
								type="file"
								accept="video/*"
								onChange={handleVideoUpload}
								hidden
							/>

							<span className="plus-button">
								<PlusIcon />
							</span>
						</label>
					</div>

					<p className="status">{status}</p>
				</main>
			)}

			{phase === "processing" && (
				<main className="stage-page">
					<h1 className="stage-title">Processing the video...</h1>

					<div className="screen-shell">
						<section className="preview-box non-clickable">
							{thumbnailURL && (
								<img
									className="preview-image"
									src={thumbnailURL}
									alt="Video first frame"
								/>
							)}
						</section>
					</div>

					<div className="progress-header">
						<span className="progress-percent">{Math.round(jobProgress)}%</span>
					</div>

					<div className="progress-track">
						<div
							className="progress-fill"
							style={{ width: `${jobProgress}%` }}
						/>
					</div>

					<section className="processing-steps">
						{processingSteps.map((step, index) => (
							<ProcessingStep
								key={step.title}
								icon={PROCESSING_STEP_ICONS[index]}
								title={step.title}
								state={step.state}
							/>
						))}
					</section>

					<p className="status">{status}</p>
				</main>
			)}

			{phase === "watching" && (
				<main className="stage-page watching-page">
					<section className="result-video-shell">
						<section className="video-box result-video-box">
							<video
								ref={videoRef}
								className="video-player"
								src={getDownloadUrl(jobId)}
								controls
							/>
						</section>

						<a
							className="download-button"
							href={getDownloadUrl(jobId)}
							download={`equalview_${jobId}.mp4`}
							aria-label="Download result video"
						>
							<DownloadIcon />
						</a>
					</section>

					{previewFrames.length > 0 && (
						<section className="frame-preview-section">
							<div className="frame-preview-header">
								<h2 className="frame-preview-title">Representative frames</h2>
								<p className="frame-preview-subtitle">
									{previewFrames.length} annotated frame
									{previewFrames.length === 1 ? "" : "s"} selected for narration
								</p>
							</div>
							<div className="frame-preview-grid">
								{previewFrames.map((frame) => (
									<FramePreviewCard
										key={`${frame.segmentId}-${frame.frame_id}-${frame.timestamp}`}
										jobId={jobId}
										frame={frame}
									/>
								))}
							</div>
						</section>
					)}

					<section className="watch-controls">
						<p className="hint">
							Analysis complete: {speechCount} speech / {silenceCount} non-speech segments
						</p>

						<button
							className={`record-button ${isListening ? "listening" : ""}`}
							onClick={toggleListening}
							aria-label={isListening ? "Stop listening" : "Start listening"}
						>
							<MicIcon />
						</button>

						<p className="hint">Press Q or click the button</p>
						<button
							type="button"
							className="hint json-download-link"
							onClick={downloadSegments}
						>
							분석 데이터(JSON) 다운로드
						</button>
						<p className="status">{status}</p>

						{stepTimings && (
							<p className="debug-timings">
								디버그 — 대사 추출 {formatSeconds(stepTimings.dialogue)} · 얼굴 인식{" "}
								{formatSeconds(stepTimings.face)} · 화면해설 생성{" "}
								{formatSeconds(stepTimings.narration)} · 음성 합성{" "}
								{formatSeconds(stepTimings.combine)}
							</p>
						)}
					</section>
				</main>
			)}
		</div>
	);
}

export default App;
