{{/*
Common naming helpers for the BOB chart.
*/}}

{{- define "bob.fullname" -}}
{{- printf "%s-bob" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "bob.chromadb.fullname" -}}
{{- printf "%s-chromadb" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "bob.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: bob
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "bob.selectorLabels" -}}
app.kubernetes.io/name: bob
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "bob.chromadb.selectorLabels" -}}
app.kubernetes.io/name: chromadb
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "bob.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "bob.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
