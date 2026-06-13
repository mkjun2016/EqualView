import { useEffect, useRef, useState } from "react";
import "./App.css";

import WaitingIcon from "./assets/waitingForVoice.jpg";
import recordingIcon from "./assets/recording.png";

function App() {
  const [videoFile, setVideoFile] = useState(null);
  const [videoURL, setVideoURL] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [status, setStatus] = useState("");

  const videoRef = useRef(null);
  const recognitionRef = useRef(null);

  function handleVideoUpload(event) {
    const file = event.target.files[0];

    if (!file) return;

    const url = URL.createObjectURL(file);

    setVideoFile(file);
    setVideoURL(url);
    setStatus("");
  }

  function startListening() {
    if (!videoFile) {
      setStatus("Please upload a video first.");
      return;
    }

    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setStatus("Speech recognition is not supported in this browser.");
      return;
    }

    const recognition = new SpeechRecognition();

    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.continuous = true;

    recognition.onstart = () => {
      setIsListening(true);
      setStatus("Listening...");
    };

    recognition.onresult = (event) => {
      const lastResultIndex = event.results.length - 1;
      const userCommand = event.results[lastResultIndex][0].transcript;

      handleUserCommand(userCommand);
    };

    recognition.onerror = (event) => {
      setIsListening(false);
      recognitionRef.current = null;

      if (event.error === "not-allowed") {
        setStatus("Microphone permission is blocked.");
        return;
      }

      if (event.error === "no-speech") {
        setStatus("No speech detected.");
        return;
      }

      setStatus(`Speech recognition error: ${event.error}`);
    };

    recognition.onend = () => {
      setIsListening(false);
      recognitionRef.current = null;
    };

    recognitionRef.current = recognition;
    recognition.start();
  }

  function stopListening() {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
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
                src={isListening ? recordingIcon: WaitingIcon}
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