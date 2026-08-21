from ultralytics import YOLO

model = YOLO("yolo26n.pt")
model.train(data = "/Users/andrewmeng/Downloads/basketball_dataset3_yolo/data.yaml", epochs=50, imgsz = 512,
            batch =32, device = "mps", project="/Users/andrewmeng/Desktop/courtIQ/runs3",name="basketball_yolo3")