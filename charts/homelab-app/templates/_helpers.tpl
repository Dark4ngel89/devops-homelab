{{/*
Numele chart-ului, trunchiat la 63 de caractere (limita Kubernetes pentru nume și label-uri).
*/}}
{{- define "homelab-app.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Numele complet al resurselor. Dacă release-ul conține deja numele chart-ului
(ex: release "homelab-app"), nu îl mai dublăm ("homelab-app-homelab-app").
*/}}
{{- define "homelab-app.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Tag-ul imaginii: image.tag dacă e setat, altfel appVersion din Chart.yaml.
*/}}
{{- define "homelab-app.imageTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Label-uri de selecție: stabile pe toată viața release-ului, pentru că selectorul unui Deployment e imuabil.
*/}}
{{- define "homelab-app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "homelab-app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Label-uri comune, puse pe toate resursele.
*/}}
{{- define "homelab-app.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "homelab-app.selectorLabels" . }}
app.kubernetes.io/version: {{ include "homelab-app.imageTag" . | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
