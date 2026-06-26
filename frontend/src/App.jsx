import { useEffect, useRef, useState } from "react";
import "./App.css";
import {
	createJob,
	deriveProcessingSteps,
	getJobSegments,
	getJobStatus,
	getProcessingProgress,
	INITIAL_PROCESSING_STEPS,
	sendVoiceCommand,
} from "./api/equalview";
import {
	PlusIcon,
	AudioIcon,
	NarrationIcon,
	OutputIcon,
	MicIcon,
	CheckIcon,
	DownloadIcon
} from "./icons/Icons";

const POLL_INTERVAL_MS = 2000;

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
	<NarrationIcon />,
	<OutputIcon />,
];

function App() {
	const [phase, setPhase] = useState("upload");
	const [videoFile, setVideoFile] = useState(null);
	const [videoURL, setVideoURL] = useState("");
	const [thumbnailURL, setThumbnailURL] = useState("");
	const [jobId, setJobId] = useState(null);
	const [segments, setSegments] = useState([]);
	const [jobProgress, setJobProgress] = useState(0);
	const [isListening, setIsListening] = useState(false);
	const [status, setStatus] = useState("");

	const videoRef = useRef(null);
	const mediaRecorderRef = useRef(null);
	const audioStreamRef = useRef(null);
	const audioChunksRef = useRef([]);

	const [processingSteps, setProcessingSteps] = useState(INITIAL_PROCESSING_STEPS);

	async function handleVideoUpload(event) {
		const file = event.target.files[0];

		if (!file) return;

		const url = URL.createObjectURL(file);

		setVideoFile(file);
		setVideoURL(url);
		setJobId(null);
		setSegments([]);
		setJobProgress(0);
		setProcessingSteps(INITIAL_PROCESSING_STEPS);
		setPhase("processing");
		setStatus("Uploading video...");

		try {
			const thumbnail = await createVideoThumbnail(file);
			setThumbnailURL(thumbnail);

			const { job_id } = await createJob(file);
			setJobId(job_id);
			setStatus("Waiting for worker...");
		} catch (error) {
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

			if (data.text) {
				handleUserCommand(data.text);
				return;
			}

			setStatus(`Backend received audio: ${data.filename}`);
		} catch (error) {
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

		if (videoURL) {
			URL.revokeObjectURL(videoURL);
		}

		setPhase("upload");
		setVideoFile(null);
		setVideoURL("");
		setThumbnailURL("");
		setJobId(null);
		setSegments([]);
		setJobProgress(0);
		setStatus("");
		setProcessingSteps(INITIAL_PROCESSING_STEPS);
	}

	useEffect(() => {
		if (phase !== "processing" || !jobId) return;

		let cancelled = false;

		async function pollJob() {
			try {
				const job = await getJobStatus(jobId);
				if (cancelled) return;

				const nextProcessingSteps = deriveProcessingSteps(job);
				setProcessingSteps(nextProcessingSteps);
				setJobProgress(getProcessingProgress(nextProcessingSteps));
				setStatus(
					job.current_step
						? job.current_step
						: ""
				);

				if (
					job.status === "COMPLETED" &&
					job.face_status === "COMPLETED" &&
					job.narration_status === "COMPLETED" &&
					job.combine_status === "COMPLETED"
				) {
					const data = await getJobSegments(jobId);
					if (cancelled) return;

					setSegments(data.segments ?? []);
					setPhase("watching");
					setStatus("");
					return;
				}

				if (job.status === "FAILED" || job.face_status === "FAILED") {
					setStatus(job.error || job.face_error || "Processing failed.");
				}
			} catch (error) {
				if (!cancelled) {
					setStatus("Failed to check job status.");
				}
			}
		}

		pollJob();
		const intervalId = setInterval(pollJob, POLL_INTERVAL_MS);

		return () => {
			cancelled = true;
			clearInterval(intervalId);
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

	useEffect(() => {
		return () => {
			if (videoURL) {
				URL.revokeObjectURL(videoURL);
			}
		};
	}, [videoURL]);

	const speechCount = segments.filter((segment) => segment.speech === true).length;
	const silenceCount = segments.filter((segment) => segment.speech === false).length;

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
								src={videoURL}
								controls
							/>
						</section>

						<button
							className="download-button"
							type="button"
							onClick={downloadSegments}
							aria-label="Download segments JSON"
						>
							<DownloadIcon />
						</button>
					</section>

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
						<p className="status">{status}</p>
					</section>
				</main>
			)}
		</div>
	);
}

export default App;
