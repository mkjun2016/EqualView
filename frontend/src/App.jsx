import { useEffect, useRef, useState } from "react";
import "./App.css";
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
			</p>
		</div>
	);
}

function App() {
	const [phase, setPhase] = useState("upload");
	const [videoFile, setVideoFile] = useState(null);
	const [videoURL, setVideoURL] = useState("");
	const [thumbnailURL, setThumbnailURL] = useState("");
	const [isListening, setIsListening] = useState(false);
	const [status, setStatus] = useState("");

	const videoRef = useRef(null);
	const mediaRecorderRef = useRef(null);
	const audioStreamRef = useRef(null);
	const audioChunksRef = useRef([]);

	const [processingSteps, setProcessingSteps] = useState([
		{ key: "extracting_audio", title: "Extracting Audio", state: "in-progress" },
		{ key: "analyzing_scenes", title: "Analyzing Scenes", state: "waiting" },
		{ key: "generating_narration", title: "Generating Narration", state: "waiting" },
		{ key: "preparing_output", title: "Preparing Output", state: "waiting" }
	]);

	async function handleVideoUpload(event) {
		const file = event.target.files[0];

		if (!file) return;

		const url = URL.createObjectURL(file);

		setVideoFile(file);
		setVideoURL(url);
		setPhase("processing");
		setStatus("Preparing video...");

		try {
			const thumbnail = await createVideoThumbnail(file);
			setThumbnailURL(thumbnail);

			await extractAudioFromVideo(file);

			setStatus("Processing completed.");

			setTimeout(() => {
				setPhase("watching");
				setStatus("");
			}, 900);
		} catch (error) {
			console.error(error);
			setStatus("Failed to process the video.");
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

	async function extractAudioFromVideo(file) {
		setStatus("Processing video...");

		const formData = new FormData();
		formData.append("video", file);

		const response = await fetch("http://localhost:8000/api/extract-audio", {
			method: "POST",
			body: formData
		});

		if (!response.ok) {
			throw new Error("Backend failed to extract audio.");
		}

		const data = await response.json();
		console.log("Extract audio response:", data);

		if (data.processing_steps) {
			setProcessingSteps([
				{
					key: "extracting_audio",
					title: "Extracting Audio",
					state: "completed"
				},
				{
					key: "analyzing_scenes",
					title: "Analyzing Scenes",
					state: "completed"
				},
				{
					key: "generating_narration",
					title: "Generating Narration",
					state: "completed"
				},
				{
					key: "preparing_output",
					title: "Preparing Output",
					state: "completed"
				}
			]);
		}

		return data;
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

				await sendVoiceToServer(audioBlob);

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

	async function sendVoiceToServer(audioBlob) {
		try {
			setStatus("Sending voice to backend...");

			const formData = new FormData();
			formData.append("audio", audioBlob, "voice.webm");

			const response = await fetch("http://localhost:8000/api/voice-command", {
				method: "POST",
				body: formData
			});

			if (!response.ok) {
				throw new Error("Backend failed.");
			}

			const data = await response.json();

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

	function goHome() {
		stopListening();

		if (videoURL) {
			URL.revokeObjectURL(videoURL);
		}

		setPhase("upload");
		setVideoFile(null);
		setVideoURL("");
		setThumbnailURL("");
		setStatus("");

		setProcessingSteps([
			{ key: "extracting_audio", title: "Extracting Audio", state: "in-progress" },
			{ key: "analyzing_scenes", title: "Analyzing Scenes", state: "waiting" },
			{ key: "generating_narration", title: "Generating Narration", state: "waiting" },
			{ key: "preparing_output", title: "Preparing Output", state: "waiting" }
		]);
	}

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

					<section className="processing-steps">
						<ProcessingStep
							icon={<AudioIcon />}
							title={processingSteps[0].title}
							state={processingSteps[0].state}
						/>

						<ProcessingStep
							icon={<SceneIcon />}
							title={processingSteps[1].title}
							state={processingSteps[1].state}
						/>

						<ProcessingStep
							icon={<NarrationIcon />}
							title={processingSteps[2].title}
							state={processingSteps[2].state}
						/>

						<ProcessingStep
							icon={<OutputIcon />}
							title={processingSteps[3].title}
							state={processingSteps[3].state}
						/>
					</section>

				
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
							onClick={() => {
								setStatus("Download will be available later.");
							}}
							aria-label="Download narrated video"
						>
							<DownloadIcon />
						</button>
					</section>

					<section className="watch-controls">
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