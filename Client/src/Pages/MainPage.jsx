import { useParams } from "react-router-dom";
import Canvas from "../components/Canvas";
import Image from "../assets/image.jpg";
// import { PieChart } from "@mui/x-charts/PieChart"
import PieArcLabel from "../components/PieChart";
import IngredientsList from "../components/IngredientList";
import response from "../components/response.json";
import { LuAudioLines } from "react-icons/lu";
import IngredientTable from "../components/Table";
import Card from "../components/Card";
import HomeImage from "../assets/homepage3.png";
import { NavLink, Link } from "react-router-dom";

function MainPage() {
  return (
    <>
      {/* <Canvas bgColor="bg-orange-100"> */}
      <section className="grid grid-cols-2 h-[96vh]">
        <div className="padding-8 bg-orange-100 flex items-center justify-center">
          <img src={HomeImage} alt="Home" className="w-[78%]" />
        </div>

        <section className="flex flex-col gap-24 items-center justify-center bg-red-150">
          <section className="flex flex-col gap-4">
            <p className="font-bold text-xl text-gray-500 italic text-center">
              Wondering what's going into your plate?
            </p>
            <p className="font-bold text-xl text-center">
              <span className="text-7xl underline decoration-orange-600 underline-offset-8 decoration-wavy decoration-4">
                Food Inspector
              </span>
            </p>
            <section className="flex flex-col gap-2 pt-4">
              <p className="font-bold text-xl text-gray-500 italic text-center">
                Analyze ingredients, nutrition, and food safety instantly using
                AI
              </p>
            </section>
          </section>

          <NavLink to="/profile">
            <button
              className="
                relative
                overflow-hidden
                px-8
                py-3
                rounded-xl
                font-semibold
                bg-gradient-to-r
                from-orange-500
                to-red-600
                text-white
                transition-all
                duration-300
                ease-in-out
                hover:scale-100
                hover:shadow-[0_12px_30px_rgba(249,115,22,0.35)]
                group
            "
            >
              <span
                className="
                    absolute
                    inset-0
                    bg-gradient-to-r
                    from-transparent
                    via-white/30
                    to-transparent
                    -translate-x-full
                    group-hover:translate-x-full
                    transition-transform
                    duration-700
                    "
              />
              <span className="relative z-10">Scan Ingredients</span>
            </button>
          </NavLink>
        </section>
      </section>
      {/* </Canvas> */}
    </>
  );
}

export default MainPage;
