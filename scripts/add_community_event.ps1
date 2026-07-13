param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$PostId,
    [Parameter(Mandatory=$true)][string]$EventType,
    [Parameter(Mandatory=$true)][string]$ActorHandle,
    [Parameter(Mandatory=$true)][string]$RawText,
    [Parameter(Mandatory=$true)][ValidateSet("positive","neutral","negative")][string]$SentimentLabel,
    [string]$ActionTaken = "none",
    [string]$OperatorReview = "pending",
    [string]$OutputPath = ".\data\community_interactions.jsonl"
)

$event = [ordered]@{
    timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
    source = $Source
    post_id = $PostId
    event_type = $EventType
    actor_handle = $ActorHandle
    raw_text = $RawText
    sentiment_label = $SentimentLabel
    action_taken = $ActionTaken
    operator_review = $OperatorReview
} | ConvertTo-Json -Compress

Add-Content -Path $OutputPath -Value $event -Encoding UTF8
Write-Host "OK: evento agregado a $OutputPath"
