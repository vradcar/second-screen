// Second Screen on Azure: Container Apps + Event Hubs + Cosmos DB (serverless) + App Insights.
// The app authenticates to every service with its system-assigned managed identity: no keys.
//
//   az deployment group create -g rg-second-screen -f infra/main.bicep \
//     -p foundryName=<your Foundry resource> image=ghcr.io/<owner>/second-screen:latest

@description('Region for new resources. Student subscriptions restrict regions; eastus is allowed.')
param location string = 'eastus'

@description('Name of the existing Foundry (AI Services) resource in this resource group.')
param foundryName string

@description('Model deployment name on the Foundry resource.')
param modelDeployment string = 'gpt-4.1-mini'

@description('Container image to run.')
param image string

@description('Agents used by the shared On-air broadcast: recorded (free), mock, or live.')
@allowed(['recorded', 'mock', 'live'])
param broadcastAgents string = 'recorded'

@description('Optional token required to start/stop broadcasts and to use live agents publicly.')
@secure()
param startToken string = ''

@description('Allow anyone to use live model calls (costs money per viewer).')
param allowPublicLive bool = false

var suffix = uniqueString(resourceGroup().id)
var tags = { project: 'second-screen' }

// ---------------------------------------------------------------- monitoring
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-secondscreen-${suffix}'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-secondscreen-${suffix}'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

// ----------------------------------------------------------------- live feed
resource eventHubs 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: 'evhns-secondscreen-${suffix}'
  location: location
  tags: tags
  sku: { name: 'Basic', tier: 'Basic', capacity: 1 }
  properties: { disableLocalAuth: true, minimumTlsVersion: '1.2' }
}

resource matchEvents 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubs
  name: 'match-events'
  properties: { partitionCount: 1, messageRetentionInDays: 1 }   // one partition keeps a match in order
}

// -------------------------------------------------------------- shared store
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-secondscreen-${suffix}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [ { name: 'EnableServerless' } ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [ { locationName: location, failoverPriority: 0 } ]
    disableLocalAuth: true
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: 'secondscreen'
  properties: { resource: { id: 'secondscreen' } }
}

resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = [for c in ['moments', 'cues', 'runs']: {
  parent: db
  name: c
  properties: { resource: { id: c, partitionKey: { paths: [ '/run_id' ], kind: 'Hash' } } }
}]

// ------------------------------------------------------------------ the app
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-secondscreen-${suffix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
  }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: foundryName
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'second-screen'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8000, transport: 'auto', allowInsecure: false }
      secrets: empty(startToken) ? [] : [ { name: 'start-token', value: startToken } ]
    }
    template: {
      containers: [
        {
          name: 'second-screen'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat([
            { name: 'AZURE_OPENAI_ENDPOINT', value: 'https://${foundryName}.openai.azure.com/' }
            { name: 'AZURE_OPENAI_DEPLOYMENT', value: modelDeployment }
            { name: 'AZURE_USE_IDENTITY', value: '1' }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'EVENTHUB_NAMESPACE', value: '${eventHubs.name}.servicebus.windows.net' }
            { name: 'EVENTHUB_NAME', value: matchEvents.name }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
            { name: 'BROADCAST_AGENTS', value: broadcastAgents }
            { name: 'ALLOW_PUBLIC_LIVE', value: allowPublicLive ? '1' : '0' }
          ], empty(startToken) ? [] : [ { name: 'BROADCAST_START_TOKEN', secretRef: 'start-token' } ])
          probes: [
            { type: 'Liveness', httpGet: { path: '/api/health', port: 8000 }, periodSeconds: 30 }
          ]
        }
      ]
      // One replica: the On-air broadcast is a single shared pipeline.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

// ------------------------------------------------- managed identity access
var eventHubsDataOwner = 'f526a384-b230-433a-b45c-95f59c4a2dec'
var openAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource ehRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(eventHubs.id, app.id, eventHubsDataOwner)
  scope: eventHubs
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', eventHubsDataOwner)
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource aiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, app.id, openAiUser)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUser)
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Cosmos DB data-plane role: Built-in Data Contributor.
resource cosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, app.id, 'data-contributor')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: app.identity.principalId
    scope: cosmos.id
  }
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
output eventHubsNamespace string = '${eventHubs.name}.servicebus.windows.net'
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output appInsightsName string = appInsights.name
