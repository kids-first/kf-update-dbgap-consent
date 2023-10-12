#!/bin/bash

# Dataservice Setup 

set -e

if [ -d "./kf-api-dataservice" ];
then
    cd kf-api-dataservice
    git pull -f
    cd ..
else
    git clone --depth 1 https://github.com/kids-first/kf-api-dataservice.git
fi
cp kf-api-dataservice/.env.sample kf-api-dataservice/.env
docker-compose -f kf-api-dataservice/docker-compose.yml up -d --build
./bin/health-check.sh
