// ======================= icons =================== //

export function PlusIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
                d="M12 5V19M5 12H19"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
            />
        </svg>
    );
}

export function AudioIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M4 10V14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M8 7V17" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M12 4V20" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M16 7V17" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M20 10V14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
    );
}


export function SceneIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect
                x="5"
                y="4"
                width="14"
                height="16"
                rx="2"
                stroke="currentColor"
                strokeWidth="2"
            />
            <path d="M9 4V20" stroke="currentColor" strokeWidth="2" />
            <path d="M15 4V20" stroke="currentColor" strokeWidth="2" />
            <path d="M5 9H19" stroke="currentColor" strokeWidth="2" />
            <path d="M5 15H19" stroke="currentColor" strokeWidth="2" />
        </svg>
    );
}

export function NarrationIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
                d="M5 19L15.5 8.5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
            />
            <path
                d="M14 7L17 10"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
            />
            <path
                d="M6 5L6.8 7.2L9 8L6.8 8.8L6 11L5.2 8.8L3 8L5.2 7.2L6 5Z"
                fill="currentColor"
            />
            <path
                d="M18 3L18.7 4.8L20.5 5.5L18.7 6.2L18 8L17.3 6.2L15.5 5.5L17.3 4.8L18 3Z"
                fill="currentColor"
            />
            <path
                d="M18 15L18.8 17.2L21 18L18.8 18.8L18 21L17.2 18.8L15 18L17.2 17.2L18 15Z"
                fill="currentColor"
            />
        </svg>
    );
}

export function OutputIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
                d="M7 3H14L19 8V21H7V3Z"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinejoin="round"
            />
            <path
                d="M14 3V8H19"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinejoin="round"
            />
        </svg>
    );
}

export function MicIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
                d="M12 14C14.2 14 16 12.2 16 10V6C16 3.8 14.2 2 12 2C9.8 2 8 3.8 8 6V10C8 12.2 9.8 14 12 14Z"
                stroke="currentColor"
                strokeWidth="2"
            />
            <path
                d="M5 10C5 13.9 8.1 17 12 17C15.9 17 19 13.9 19 10"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
            />
            <path d="M12 17V21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            <path d="M9 21H15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
    );
}

export function DownloadIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
                d="M12 3V15"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
            />
            <path
                d="M7 10L12 15L17 10"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
            <path
                d="M5 21H19"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
            />
        </svg>
    );
}

export function CheckIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
                d="M20 6L9 17L4 12"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </svg>
    );
}

export function ProcessingStep({ icon, title, state }) {
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
// ==================================================== //