import { useEffect, useRef, useState } from "react";
import "./App.css";

import WaitingIcon from "./icons/waitingForVoice.jpg";
import recordingIcon from "./icons/recording.png";

function App() {
	const [videoFile, setVideoFile] = useState(null);
	const [videoURL, setVideoURL] = useState("");
	const [isListening, setIsListening] = useState(false);
	const [status, setStatus] = useState("");

	const videoRef = useRef(null);
	const mediaRecorderRef = useRef(null);
	const audioStreamRef = useRef(null);
	const audioChunksRef = useRef([]);

	function handleVideoUpload(event) {
		const file = event.target.files[0];

		if (!file) return;

		const url = URL.createObjectURL(file);

		setVideoFile(file);
		setVideoURL(url);
		setStatus("");
	}

	function speak(text) {
		if (!window.speechSynthesis) {
			return;
		}

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
		setStatus("Recording stopped.");
		speak("Recording stopped.");
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

			const response = await fetch("http://127.0.0.1:8000/api/voice-command", {
				method: "POST",
				body: formData
			});

			if (!response.ok) {
				throw new Error("Backend failed.");
			}

			const data = await response.json();

			console.log("Backend response:", data);
			setStatus(`Backend received audio: ${data.filename}`);
		} catch (error) {
			console.error(error);
			setStatus("Failed to send voice to backend.");
		}
	}












	async function extractAudioFromVideo() {
		if (!videoFile) {
			setStatus("Please upload a video first.");
			return;
		}

		try {
			setStatus("Sending video to backend...");

			const formData = new FormData();
			formData.append("video", videoFile);

			const response = await fetch("http://127.0.0.1:8000/api/extract-audio", {
				method: "POST",
				body: formData
			});

			if (!response.ok) {
				throw new Error("Backend failed to extract audio.");
			}

			const data = await response.json();

			console.log("Extract audio response:", data);

			setStatus(
				`Audio extracted. JSON saved: ${data.json_file}`
			);
		} catch (error) {
			console.error(error);
			setStatus("Failed to extract audio from video.");
		}
	}

	function goHome() {
		stopListening();

		if (videoURL) {
			URL.revokeObjectURL(videoURL);
		}

		setVideoFile(null);
		setVideoURL("");
		setStatus("");
	}

	useEffect(() => {
		function handleKeyDown(event) {
			if (event.repeat) return;

			if (event.key.toLowerCase() === "q") {
				event.preventDefault();
				toggleListening();
			}
		}

		window.addEventListener("keydown", handleKeyDown);

		return () => {
			window.removeEventListener("keydown", handleKeyDown);
		};
	}, [isListening, videoFile]);

	useEffect(() => {
		return () => {
			if (videoURL) {
				URL.revokeObjectURL(videoURL);
			}
		};
	}, [videoURL]);

	return (
		<div className="app">
			{!videoFile ? (
				<main className="upload-page">
					<section className="upload-card">
						<h1>EqualView</h1>
						<p>Upload a video from your folder.</p>

						<label className="upload-box">
							Choose Video
							<input
								type="file"
								accept="video/*"
								onChange={handleVideoUpload}
								hidden
							/>
						</label>

						<p className="status">{status}</p>
					</section>
				</main>
			) : (
				<main className="player-page">
					<header className="player-header">
						<button className="brand-button" onClick={goHome}>
							EqualView
						</button>
					</header>

					<section className="video-section">
						<video
							ref={videoRef}
							className="video-player"
							src={videoURL}
							controls
						/>
					</section>

					<section className="control-area">
						<button
							className={`record-button ${isListening ? "listening" : ""}`}
							onClick={toggleListening}
							aria-label={isListening ? "Stop listening" : "Start listening"}
						>
							<img
								src={isListening ? recordingIcon : WaitingIcon}
								alt=""
								className="record-icon"
							/>
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